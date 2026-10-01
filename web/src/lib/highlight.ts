// A small, dependency-free syntax highlighter for Python and TypeScript/JavaScript.
// Line-oriented with carried state for multi-line strings and block comments, which is
// all a diff/source viewer needs.

export type TokenType = "kw" | "str" | "com" | "num" | "fn" | "dec" | "bi" | "txt";

export interface Token {
  t: TokenType;
  v: string;
}

const PY_KW = new Set(
  "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case".split(
    " ",
  ),
);
const PY_BI = new Set(
  "print len range dict list set tuple str int float bool open isinstance super self cls enumerate zip sorted min max sum any all".split(
    " ",
  ),
);
const JS_KW = new Set(
  "abstract as async await break case catch class const continue debugger default delete do else enum export extends false finally for from function get if implements import in instanceof interface let new null of private protected public readonly return set static super switch this throw true try type typeof undefined var void while with yield".split(
    " ",
  ),
);
const JS_BI = new Set(
  "console Promise Array Object String Number JSON Math Error Map Set".split(" "),
);

export type Lang = "python" | "typescript" | "javascript" | "text";

export function languageOf(path: string): Lang {
  const ext = path.slice(path.lastIndexOf(".") + 1).toLowerCase();
  if (ext === "py" || ext === "pyi") return "python";
  if (["ts", "tsx", "mts", "cts"].includes(ext)) return "typescript";
  if (["js", "jsx", "mjs", "cjs"].includes(ext)) return "javascript";
  return "text";
}

interface State {
  inString: string | null; // the closing delimiter of an open multi-line string
  inComment: boolean;
}

const IDENT = /[A-Za-z_$][\w$]*/y;
const NUMBER = /(?:0x[\da-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:e[+-]?\d+)?)n?/y;

function push(out: Token[], t: TokenType, v: string): void {
  const last = out[out.length - 1];
  if (last && last.t === t && t === "txt") last.v += v;
  else if (v) out.push({ t, v });
}

function tokenizeLine(line: string, lang: Lang, state: State): Token[] {
  const out: Token[] = [];
  if (lang === "text") return [{ t: "txt", v: line }];
  const py = lang === "python";
  const kw = py ? PY_KW : JS_KW;
  const bi = py ? PY_BI : JS_BI;
  let i = 0;

  if (state.inString) {
    const end = line.indexOf(state.inString);
    if (end === -1) return [{ t: "str", v: line }];
    push(out, "str", line.slice(0, end + state.inString.length));
    i = end + state.inString.length;
    state.inString = null;
  }
  if (state.inComment) {
    const end = line.indexOf("*/");
    if (end === -1) return [{ t: "com", v: line }];
    push(out, "com", line.slice(0, end + 2));
    i = end + 2;
    state.inComment = false;
  }

  while (i < line.length) {
    const ch = line[i] ?? "";
    const rest = line.slice(i);
    if ((py && ch === "#") || (!py && rest.startsWith("//"))) {
      push(out, "com", rest);
      break;
    }
    if (!py && rest.startsWith("/*")) {
      const end = line.indexOf("*/", i + 2);
      if (end === -1) {
        push(out, "com", rest);
        state.inComment = true;
        break;
      }
      push(out, "com", line.slice(i, end + 2));
      i = end + 2;
      continue;
    }
    if (py && ch === "@" && /^\s*$/.test(line.slice(0, i))) {
      push(out, "dec", rest);
      break;
    }
    const prefix = py ? (/^[rbfuRBFU]{0,2}(?="""|'''|"|')/.exec(rest)?.[0] ?? "") : "";
    const q = line[i + prefix.length] ?? "";
    if (q === '"' || q === "'" || (!py && q === "`")) {
      const triple = py && line.startsWith(q.repeat(3), i + prefix.length);
      const delim = triple ? q.repeat(3) : q;
      let j = i + prefix.length + delim.length;
      let closed = false;
      while (j < line.length) {
        if (line[j] === "\\") {
          j += 2;
          continue;
        }
        if (line.startsWith(delim, j)) {
          j += delim.length;
          closed = true;
          break;
        }
        j += 1;
      }
      push(out, "str", line.slice(i, j));
      if (!closed && (triple || q === "`")) state.inString = delim;
      i = j;
      continue;
    }
    NUMBER.lastIndex = i;
    if (/[0-9]/.test(ch) && NUMBER.test(line)) {
      push(out, "num", line.slice(i, NUMBER.lastIndex));
      i = NUMBER.lastIndex;
      continue;
    }
    IDENT.lastIndex = i;
    if (/[A-Za-z_$]/.test(ch) && IDENT.test(line)) {
      const word = line.slice(i, IDENT.lastIndex);
      i = IDENT.lastIndex;
      if (kw.has(word)) push(out, "kw", word);
      else if (bi.has(word)) push(out, "bi", word);
      else if (line[i] === "(") push(out, "fn", word);
      else push(out, "txt", word);
      continue;
    }
    push(out, "txt", ch);
    i += 1;
  }
  return out;
}

/** Highlight a sequence of lines, carrying multi-line string/comment state across them. */
export function highlightLines(lines: string[], lang: Lang): Token[][] {
  const state: State = { inString: null, inComment: false };
  return lines.map((line) => tokenizeLine(line, lang, state));
}
