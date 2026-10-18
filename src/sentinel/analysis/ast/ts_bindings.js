/* Lexical variable access for the TS/JS extractor. Never loads project config or files. */
'use strict';

function localChecker(ts, sf) {
  const host = {
    getSourceFile: (name) => name === sf.fileName ? sf : undefined,
    getDefaultLibFileName: () => '',
    writeFile: () => {},
    getCurrentDirectory: () => '',
    getDirectories: () => [],
    fileExists: (name) => name === sf.fileName,
    readFile: () => undefined,
    getCanonicalFileName: (name) => name,
    useCaseSensitiveFileNames: () => true,
    getNewLine: () => '\n',
  };
  const options = { noLib: true, noResolve: true, allowJs: true };
  return ts.createProgram([sf.fileName], options, host).getTypeChecker();
}

function moduleBinding(ts, checker, node) {
  const symbol = checker.getSymbolAtLocation(node);
  return !!symbol && (symbol.declarations || []).some((decl) =>
    ts.isImportSpecifier(decl) || ts.isImportClause(decl) || ts.isNamespaceImport(decl) ||
    (ts.isVariableDeclaration(decl) && decl.parent && decl.parent.parent &&
      ts.isVariableStatement(decl.parent.parent) && ts.isSourceFile(decl.parent.parent.parent)));
}

function accessOperations(ts, node) {
  const parent = node.parent;
  if (ts.isBinaryExpression(parent) && parent.left === node &&
      parent.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
      parent.operatorToken.kind <= ts.SyntaxKind.LastAssignment) {
    return parent.operatorToken.kind === ts.SyntaxKind.EqualsToken ? ['write'] : ['read', 'write'];
  }
  if ((ts.isPrefixUnaryExpression(parent) || ts.isPostfixUnaryExpression(parent)) &&
      [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(parent.operator)) {
    return ['read', 'write'];
  }
  return ['read'];
}

function bindingAccesses(ts, sf) {
  const checker = localChecker(ts, sf);
  return (node, owner) => {
    let name;
    if (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.expression) &&
        moduleBinding(ts, checker, node.expression)) {
      name = `${node.expression.text}.${node.name.text}`;
    } else if (ts.isIdentifier(node) && moduleBinding(ts, checker, node)) {
      const symbol = checker.getSymbolAtLocation(node);
      if (symbol.declarations.some((decl) => decl.name === node)) return [];
      name = node.text;
    }
    if (!name) return [];
    return accessOperations(ts, node).map((operation) => ({
      symbol: owner, name, operation,
      line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
    }));
  };
}

module.exports = { bindingAccesses };
