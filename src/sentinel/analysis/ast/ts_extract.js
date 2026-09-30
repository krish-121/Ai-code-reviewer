#!/usr/bin/env node
/*
 * Sentinel TypeScript/JavaScript extractor.
 *
 * Uses the TypeScript compiler API (parser only, no type checking) to extract the same
 * language-neutral structure the Python analyzer produces: symbols, imports, call
 * sites, HTTP endpoints and database operations.
 *
 * stdin:  {"files": [{"path": "src/a.ts", "source": "..."}]}
 * stdout: [FileSymbols, ...]  (snake_case keys, see sentinel/core/domain/code.py)
 */
'use strict';

let ts;
try {
  ts = require(process.env.SENTINEL_TS_MODULE || 'typescript');
} catch (err) {
  process.stderr.write('sentinel: the "typescript" package could not be resolved\n');
  process.exit(3);
}

const HTTP_METHODS = new Set(['get', 'post', 'put', 'delete', 'patch', 'head', 'options', 'all']);
const ROUTER_HINT = /^(app|router|server|api|fastify|route|routes|r)$/i;
const LOOP_CALLBACKS = new Set(['forEach', 'map', 'filter', 'reduce', 'flatMap', 'some', 'every', 'find', 'findIndex']);
const DB_EXEC = new Set(['query', 'execute', 'raw', '$queryRaw', '$executeRaw', '$queryRawUnsafe', '$executeRawUnsafe', 'unsafe']);
const ORM_READ = new Set(['findMany', 'findUnique', 'findFirst', 'findOne', 'findAll', 'findById', 'findByPk', 'find', 'count', 'aggregate', 'select', 'where', 'first']);
const ORM_WRITE = new Set(['create', 'createMany', 'update', 'updateMany', 'upsert', 'delete', 'deleteMany', 'insert', 'save', 'destroy', 'remove', 'insertOne', 'insertMany', 'updateOne', 'deleteOne', 'bulkCreate']);
const DB_HINTS = ['db', 'pool', 'client', 'prisma', 'knex', 'conn', 'connection', 'repo', 'repository', 'model', 'collection', 'sequelize', 'tx', 'sql', 'database'];
const SQL_VERB = /^\s*(select|with|insert|update|delete|replace|merge|create|drop|alter)\b/i;
const SQL_TABLE = /\b(?:from|into|update|join)\s+[`"[]?([A-Za-z_][\w.]*)/gi;
const TEST_FILE = /(\.(test|spec)\.[cm]?[jt]sx?$)|(^|\/)__tests__\//;
const NEXT_ROUTE_FILE = /(^|\/)app\/(.+\/)?route\.[cm]?[jt]sx?$/;

function lineOf(sf, pos) {
  return sf.getLineAndCharacterOfPosition(pos).line + 1;
}

function calleeName(expr) {
  if (!expr) return '';
  switch (expr.kind) {
    case ts.SyntaxKind.Identifier:
    case ts.SyntaxKind.PrivateIdentifier:
      return expr.text;
    case ts.SyntaxKind.ThisKeyword:
      return 'this';
    case ts.SyntaxKind.SuperKeyword:
      return 'super';
    case ts.SyntaxKind.PropertyAccessExpression: {
      const base = calleeName(expr.expression);
      return base ? `${base}.${expr.name.text}` : expr.name.text;
    }
    case ts.SyntaxKind.CallExpression:
    case ts.SyntaxKind.ElementAccessExpression:
    case ts.SyntaxKind.NonNullExpression:
    case ts.SyntaxKind.ParenthesizedExpression:
    case ts.SyntaxKind.AsExpression:
    case ts.SyntaxKind.SatisfiesExpression:
    case ts.SyntaxKind.TypeAssertionExpression:
      return calleeName(expr.expression);
    default:
      return '';
  }
}

function literalText(node) {
  if (!node) return null;
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  if (ts.isTemplateExpression(node)) {
    return node.head.text + node.templateSpans.map((s) => '{}' + s.literal.text).join('');
  }
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    return (literalText(node.left) || '{}') + (literalText(node.right) || '{}');
  }
  return null;
}

function classifySql(sql) {
  if (!sql) return 'unknown';
  const m = SQL_VERB.exec(sql);
  if (!m) return 'unknown';
  const verb = m[1].toLowerCase();
  return verb === 'select' || verb === 'with' ? 'read' : 'write';
}

function sqlTables(sql) {
  if (!sql) return [];
  const out = [];
  let m;
  SQL_TABLE.lastIndex = 0;
  while ((m = SQL_TABLE.exec(sql)) !== null) {
    const t = m[1].split('.').pop().toLowerCase();
    if (!out.includes(t)) out.push(t);
  }
  return out;
}

function hasModifier(node, kind) {
  const mods = ts.canHaveModifiers && ts.canHaveModifiers(node) ? ts.getModifiers(node) : node.modifiers;
  return !!(mods && mods.some((m) => m.kind === kind));
}

function paramNames(fn) {
  return (fn.parameters || []).map((p) => (ts.isIdentifier(p.name) ? p.name.text : p.name.getText()));
}

function decoratorNames(node) {
  const decos = ts.canHaveDecorators && ts.canHaveDecorators(node) ? ts.getDecorators(node) : node.decorators;
  return (decos || []).map((d) => calleeName(d.expression) || d.expression.getText());
}

function isFunctionLike(node) {
  return node && (ts.isArrowFunction(node) || ts.isFunctionExpression(node));
}

function extract(path, source) {
  const kind = /\.tsx$/.test(path) ? ts.ScriptKind.TSX
    : /\.[cm]?ts$/.test(path) ? ts.ScriptKind.TS
    : /\.jsx$/.test(path) ? ts.ScriptKind.JSX : ts.ScriptKind.JS;
  const language = kind === ts.ScriptKind.TS || kind === ts.ScriptKind.TSX ? 'typescript' : 'javascript';
  const sf = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, kind);
  const isTest = TEST_FILE.test(path);
  const result = {
    path,
    language,
    module_name: path.replace(/\.[cm]?[jt]sx?$/, '').replace(/\/index$/, ''),
    symbols: [],
    imports: [],
    calls: [],
    endpoints: [],
    db_operations: [],
    is_test_file: isTest,
    parse_error: null,
    loc: source.split('\n').length - (source.endsWith('\n') ? 1 : 0),
  };
  const diags = sf.parseDiagnostics || [];
  if (diags.length) {
    const d = diags[0];
    const msg = ts.flattenDiagnosticMessageText(d.messageText, ' ');
    result.parse_error = `${msg} (line ${lineOf(sf, d.start || 0)})`;
  }

  const exportedNames = new Set();
  const scope = []; // {qn, kind}
  let loopDepth = 0;
  const describe = [];

  const current = () => (scope.length ? scope[scope.length - 1].qn : '<module>');
  const classScope = () => {
    for (let i = scope.length - 1; i >= 0; i--) if (scope[i].kind === 'class') return scope[i].qn;
    return null;
  };
  const qualify = (name) => (scope.length ? `${current()}.${name}` : name);

  function addSymbol(node, name, symKind, extra) {
    const sym = Object.assign({
      name,
      qualified_name: qualify(name),
      kind: symKind,
      line_start: lineOf(sf, node.getStart(sf)),
      line_end: lineOf(sf, node.getEnd()),
      parent: classScope(),
      decorators: decoratorNames(node),
      params: [],
      bases: [],
      is_async: hasModifier(node, ts.SyntaxKind.AsyncKeyword),
      exported: hasModifier(node, ts.SyntaxKind.ExportKeyword),
    }, extra || {});
    result.symbols.push(sym);
    return sym;
  }

  function withScope(qn, symKind, fn) {
    scope.push({ qn, kind: symKind });
    const savedLoop = loopDepth;
    loopDepth = 0;
    fn();
    loopDepth = savedLoop;
    scope.pop();
  }

  function visitFunctionBody(body, sym) {
    withScope(sym.qualified_name, sym.kind, () => {
      if (body && ts.isBlock(body)) ts.forEachChild(body, visit);
      else visit(body); // concise arrow body: `() => expr`
    });
  }

  function recordImport(spec, names, aliases, node) {
    result.imports.push({ module: spec, names, aliases, line: lineOf(sf, node.getStart(sf)), level: 0 });
  }

  function recordCall(node, callee, awaited) {
    if (!callee) return;
    result.calls.push({
      caller: current(),
      callee,
      line: lineOf(sf, node.getStart(sf)),
      in_loop: loopDepth > 0,
      awaited,
    });
  }

  function maybeDb(node, callee, firstArg, tagged) {
    const parts = callee.split('.');
    const method = parts[parts.length - 1];
    const receiver = parts.slice(0, -1).join('.').toLowerCase();
    const hinted = DB_HINTS.some((h) => receiver.split('.').some((p) => p.includes(h)));
    let op = null;
    let sql = null;
    if (DB_EXEC.has(method) && (hinted || tagged || SQL_VERB.test(literalText(firstArg) || ''))) {
      sql = literalText(firstArg);
      op = classifySql(sql);
    } else if (hinted && ORM_READ.has(method)) {
      op = 'read';
    } else if (hinted && ORM_WRITE.has(method)) {
      op = 'write';
    }
    if (!op) return;
    const tables = sqlTables(sql);
    result.db_operations.push({
      function: current(),
      operation: op,
      line: lineOf(sf, node.getStart(sf)),
      detail: callee + (tables.length ? ` [${tables.join(', ')}]` : '') + (tagged ? ' (tagged template)' : ''),
      in_loop: loopDepth > 0,
    });
  }

  function maybeEndpoint(node, callee) {
    const parts = callee.split('.');
    if (parts.length !== 2) return false;
    const [recv, method] = parts;
    if (!ROUTER_HINT.test(recv) || !HTTP_METHODS.has(method.toLowerCase())) return false;
    const args = node.arguments;
    if (!args.length) return false;
    const route = literalText(args[0]);
    if (route === null || !route.startsWith('/')) return false;
    const handlerArg = args[args.length - 1];
    const verb = method.toUpperCase() === 'ALL' ? 'ANY' : method.toUpperCase();
    if (isFunctionLike(handlerArg)) {
      const name = `${verb} ${route}`;
      const sym = addSymbol(handlerArg, name, 'function', {
        params: paramNames(handlerArg),
        is_async: hasModifier(handlerArg, ts.SyntaxKind.AsyncKeyword),
        decorators: ['route'],
      });
      result.endpoints.push({ method: verb, route, handler: sym.qualified_name, line: lineOf(sf, node.getStart(sf)) });
      // Middleware args (all but the last) are visited normally.
      for (const a of args.slice(1, -1)) visit(a);
      visitFunctionBody(handlerArg.body, sym);
      return true;
    }
    const handler = calleeName(handlerArg);
    if (handler) {
      result.endpoints.push({ method: verb, route, handler, line: lineOf(sf, node.getStart(sf)) });
      recordCall(node, handler, false);
    }
    return false;
  }

  function handleTestCall(node, callee) {
    const fnName = callee.split('.')[0];
    if (!isTest || !['describe', 'it', 'test'].includes(fnName)) return false;
    const title = literalText(node.arguments[0]);
    const body = node.arguments.find(isFunctionLike);
    if (title === null || !body) return false;
    if (fnName === 'describe') {
      describe.push(title);
      visit(body.body);
      describe.pop();
      return true;
    }
    const name = [...describe, title].join(' > ');
    const sym = addSymbol(body, name, 'test', { qualified_name: name, parent: null });
    visitFunctionBody(body.body, sym);
    return true;
  }

  function visit(node) {
    if (!node) return;
    switch (node.kind) {
      case ts.SyntaxKind.ImportDeclaration: {
        const spec = node.moduleSpecifier.text;
        const names = [];
        const aliases = {};
        const clause = node.importClause;
        if (clause) {
          if (clause.name) { names.push('default'); aliases[clause.name.text] = 'default'; }
          const nb = clause.namedBindings;
          if (nb && ts.isNamespaceImport(nb)) { names.push('*'); aliases[nb.name.text] = '*'; }
          if (nb && ts.isNamedImports(nb)) {
            for (const el of nb.elements) {
              const imported = (el.propertyName || el.name).text;
              names.push(imported);
              aliases[el.name.text] = imported;
            }
          }
        }
        recordImport(spec, names, aliases, node);
        return;
      }
      case ts.SyntaxKind.ExportDeclaration: {
        if (node.moduleSpecifier) {
          const names = node.exportClause && ts.isNamedExports(node.exportClause)
            ? node.exportClause.elements.map((e) => (e.propertyName || e.name).text) : ['*'];
          recordImport(node.moduleSpecifier.text, names, {}, node);
        } else if (node.exportClause && ts.isNamedExports(node.exportClause)) {
          for (const el of node.exportClause.elements) exportedNames.add((el.propertyName || el.name).text);
        }
        return;
      }
      case ts.SyntaxKind.ExportAssignment:
        if (ts.isIdentifier(node.expression)) exportedNames.add(node.expression.text);
        visit(node.expression);
        return;
      case ts.SyntaxKind.FunctionDeclaration: {
        if (!node.name) { ts.forEachChild(node, visit); return; }
        const inClass = scope.length && scope[scope.length - 1].kind === 'class';
        const sym = addSymbol(node, node.name.text, inClass ? 'method' : 'function', { params: paramNames(node) });
        if (sym.exported && NEXT_ROUTE_FILE.test(path) && /^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$/.test(sym.name)) {
          const route = '/' + (path.match(NEXT_ROUTE_FILE)[2] || '').replace(/\/$/, '');
          result.endpoints.push({ method: sym.name, route, handler: sym.qualified_name, line: sym.line_start });
        }
        if (node.body) visitFunctionBody(node.body, sym);
        return;
      }
      case ts.SyntaxKind.ClassDeclaration:
      case ts.SyntaxKind.ClassExpression: {
        const name = node.name ? node.name.text : '<anonymous class>';
        const bases = [];
        for (const clause of node.heritageClauses || []) {
          for (const t of clause.types) bases.push(calleeName(t.expression) || t.expression.getText());
        }
        const sym = addSymbol(node, name, 'class', { bases });
        withScope(sym.qualified_name, 'class', () => {
          for (const member of node.members) visit(member);
        });
        return;
      }
      case ts.SyntaxKind.MethodDeclaration:
      case ts.SyntaxKind.Constructor:
      case ts.SyntaxKind.GetAccessor:
      case ts.SyntaxKind.SetAccessor: {
        const name = node.kind === ts.SyntaxKind.Constructor ? 'constructor'
          : (node.name && (node.name.text || node.name.getText())) || '<method>';
        const sym = addSymbol(node, name, 'method', { params: paramNames(node) });
        if (node.body) visitFunctionBody(node.body, sym);
        return;
      }
      case ts.SyntaxKind.PropertyDeclaration: {
        if (node.initializer && isFunctionLike(node.initializer) && node.name) {
          const sym = addSymbol(node, node.name.text || node.name.getText(), 'method', {
            params: paramNames(node.initializer),
            is_async: hasModifier(node.initializer, ts.SyntaxKind.AsyncKeyword),
          });
          visitFunctionBody(node.initializer.body, sym);
          return;
        }
        ts.forEachChild(node, visit);
        return;
      }
      case ts.SyntaxKind.VariableStatement: {
        const exported = hasModifier(node, ts.SyntaxKind.ExportKeyword);
        for (const decl of node.declarationList.declarations) {
          const init = decl.initializer;
          if (ts.isIdentifier(decl.name) && isFunctionLike(init)) {
            const sym = addSymbol(decl, decl.name.text, scope.length && scope[scope.length - 1].kind === 'class' ? 'method' : 'function', {
              params: paramNames(init),
              is_async: hasModifier(init, ts.SyntaxKind.AsyncKeyword),
              exported,
            });
            visitFunctionBody(init.body, sym);
            continue;
          }
          // require(): const x = require('y') / const {a, b: c} = require('y')
          if (init && ts.isCallExpression(init) && ts.isIdentifier(init.expression) &&
              init.expression.text === 'require' && init.arguments.length && ts.isStringLiteral(init.arguments[0])) {
            const spec = init.arguments[0].text;
            const aliases = {};
            const names = [];
            if (ts.isIdentifier(decl.name)) { aliases[decl.name.text] = '*'; names.push('*'); }
            else if (ts.isObjectBindingPattern(decl.name)) {
              for (const el of decl.name.elements) {
                const imported = el.propertyName ? el.propertyName.getText() : el.name.getText();
                names.push(imported);
                aliases[el.name.getText()] = imported;
              }
            }
            recordImport(spec, names, aliases, decl);
            continue;
          }
          if (!scope.length && ts.isIdentifier(decl.name)) {
            addSymbol(decl, decl.name.text, 'variable', { exported });
          }
          if (init) visit(init);
        }
        return;
      }
      case ts.SyntaxKind.BinaryExpression: {
        // module.exports = X / exports.foo = X
        const left = calleeName(node.left);
        if (node.operatorToken.kind === ts.SyntaxKind.EqualsToken && /^(module\.)?exports(\.|$)/.test(left)) {
          if (ts.isIdentifier(node.right)) exportedNames.add(node.right.text);
          if (ts.isObjectLiteralExpression(node.right)) {
            for (const prop of node.right.properties) {
              if (ts.isShorthandPropertyAssignment(prop)) exportedNames.add(prop.name.text);
              else if (ts.isPropertyAssignment(prop) && ts.isIdentifier(prop.initializer)) exportedNames.add(prop.initializer.text);
            }
          }
          const tail = left.split('.').pop();
          if (tail && tail !== 'exports') exportedNames.add(tail);
          if (isFunctionLike(node.right) && tail && tail !== 'exports') {
            const sym = addSymbol(node, tail, 'function', { params: paramNames(node.right), exported: true });
            visitFunctionBody(node.right.body, sym);
            return;
          }
        }
        ts.forEachChild(node, visit);
        return;
      }
      case ts.SyntaxKind.ForStatement:
      case ts.SyntaxKind.ForInStatement:
      case ts.SyntaxKind.ForOfStatement:
      case ts.SyntaxKind.WhileStatement:
      case ts.SyntaxKind.DoStatement: {
        if (node.initializer) visit(node.initializer);
        if (node.expression) visit(node.expression);
        if (node.condition) visit(node.condition);
        if (node.incrementor) visit(node.incrementor);
        loopDepth++;
        visit(node.statement);
        loopDepth--;
        return;
      }
      case ts.SyntaxKind.NewExpression: {
        recordCall(node, calleeName(node.expression), false);
        ts.forEachChild(node, visit);
        return;
      }
      case ts.SyntaxKind.TaggedTemplateExpression: {
        const callee = calleeName(node.tag);
        recordCall(node, callee, node.parent && ts.isAwaitExpression(node.parent));
        maybeDb(node, callee, node.template, true);
        ts.forEachChild(node, visit);
        return;
      }
      case ts.SyntaxKind.CallExpression: {
        const callee = calleeName(node.expression);
        if (handleTestCall(node, callee)) return;
        if (maybeEndpoint(node, callee)) return;
        const awaited = !!(node.parent && ts.isAwaitExpression(node.parent));
        recordCall(node, callee, awaited);
        maybeDb(node, callee, node.arguments[0], false);
        visit(node.expression);
        const method = callee.split('.').pop();
        for (const arg of node.arguments) {
          if (LOOP_CALLBACKS.has(method) && isFunctionLike(arg)) {
            loopDepth++;
            visit(arg);
            loopDepth--;
          } else {
            visit(arg);
          }
        }
        return;
      }
      default:
        ts.forEachChild(node, visit);
    }
  }

  visit(sf);
  for (const sym of result.symbols) {
    if (!sym.parent && exportedNames.has(sym.name)) sym.exported = true;
  }
  result.symbols.unshift({
    name: result.module_name.split('/').pop() || path,
    qualified_name: '<module>',
    kind: 'module',
    line_start: 1,
    line_end: Math.max(result.loc, 1),
    parent: null,
    decorators: [],
    params: [],
    bases: [],
    is_async: false,
    exported: false,
  });
  return result;
}

function main() {
  const chunks = [];
  process.stdin.on('data', (c) => chunks.push(c));
  process.stdin.on('end', () => {
    let input;
    try {
      input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    } catch (err) {
      process.stderr.write('sentinel: invalid JSON on stdin\n');
      process.exit(2);
    }
    const out = [];
    for (const f of input.files || []) {
      try {
        out.push(extract(f.path, f.source));
      } catch (err) {
        out.push({ path: f.path, language: /\.[cm]?tsx?$/.test(f.path) ? 'typescript' : 'javascript',
          module_name: f.path, symbols: [], imports: [], calls: [], endpoints: [], db_operations: [],
          is_test_file: false, parse_error: `extractor crashed: ${err && err.message}`, loc: 0 });
      }
    }
    process.stdout.write(JSON.stringify(out));
  });
}

main();
