// Fixed trusted TypeScript 7 native bridge. Application source is data in a closed VFS.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';

const MAX_FACTS = 20000;
const MAX_NODES = 200000;
const ROOT = '/work/';
const packagePath = process.argv[2];
const nativePath = process.argv[3];
const require = createRequire(`${packagePath}/package.json`);
const load = name => import(pathToFileURL(require.resolve(name)).href);
const [{ API, SymbolFlags }, { SyntaxKind: K }] =
  await Promise.all(['typescript/unstable/sync', 'typescript/unstable/ast'].map(load));
const input = JSON.parse(readFileSync(0, 'utf8'));
if (input.version !== 1 || !Array.isArray(input.sources) || input.sources.length > 1000)
  throw new Error('Invalid snapshot envelope');
const sources = new Map(input.sources.map(source => [ROOT + source.path, source]));
const files = Object.fromEntries([...sources].map(([path, source]) => [path, source.text]));
files[ROOT + 'tsconfig.json'] = JSON.stringify({
  compilerOptions: { noLib: true, noResolve: false, allowJs: true, checkJs: true,
    module: 'ESNext', moduleResolution: 'Bundler', jsx: 'preserve', noEmit: true,
    types: [], skipLibCheck: true, allowImportingTsExtensions: true },
  files: [...sources.keys()],
});
const contents = new Map(Object.entries(files));
const directories = new Map([['/', { files: [], directories: [] }]]);
for (const filePath of contents.keys()) {
  const parts = filePath.slice(1).split('/');
  let parent = '/';
  for (let index = 0; index < parts.length; index++) {
    const name = parts[index];
    const directory = directories.get(parent);
    if (index === parts.length - 1) directory.files.push(name);
    else {
      const child = parent + name + '/';
      if (!directories.has(child)) {
        directory.directories.push(name);
        directories.set(child, { files: [], directories: [] });
      }
      parent = child;
    }
  }
}
const directory = path => directories.get(path.endsWith('/') ? path : path + '/');
// Returning undefined permits native real-filesystem fallback. Close every callback.
// Maps also preserve valid source directory names such as constructor and __proto__.
const fs = {
  readFile: path => contents.get(path) ?? null,
  fileExists: path => contents.has(path),
  directoryExists: path => directory(path) !== undefined,
  getAccessibleEntries: path => directory(path) ?? { files: [], directories: [] },
  realpath: path => path,
};
if (fs.readFile(`${packagePath}/package.json`) !== null || fs.directoryExists(packagePath)
    || fs.getAccessibleEntries(packagePath).files.length !== 0)
  throw new Error('Virtual filesystem must be closed');
const api = new API({ cwd: ROOT, fs, tsserverPath: nativePath });
const rows = { symbols: [], calls: [], imports: [], references: [] };
const coverage = { files_analyzed: 0, parse_errors: 0, nodes_visited: 0, facts_truncated: 0 };
let factCount = 0;
const definitions = new Map();
const pending = [];
const declarationKinds = new Set(['FunctionDeclaration', 'ClassDeclaration', 'InterfaceDeclaration',
  'TypeAliasDeclaration', 'EnumDeclaration', 'EnumMember', 'ModuleDeclaration', 'VariableDeclaration',
  'MethodDeclaration', 'MethodSignature', 'PropertyDeclaration', 'PropertySignature', 'Parameter',
  'GetAccessor', 'SetAccessor', 'TypeParameter'].map(name => K[name]));
const kindNames = Object.fromEntries(Object.entries(K).filter(([, value]) => typeof value === 'number')
  .map(([name, value]) => [value, name]));
function add(group, row) {
  if (factCount >= MAX_FACTS) { coverage.facts_truncated++; return; }
  rows[group].push(row); factCount++;
}
function span(node) {
  const file = node.getSourceFile();
  const source = sources.get(file.fileName);
  if (!source) return undefined;
  const start = node.getStart(file);
  const end = node.getEnd();
  return { path: source.path, start, end,
    start_line: file.getLineAndCharacterOfPosition(start).line + 1,
    end_line: file.getLineAndCharacterOfPosition(Math.max(start, end - 1)).line + 1,
    source_hash: source.source_hash };
}
function key(info) { return JSON.stringify([info.path, info.start, info.end]); }
function define(node, name) {
  const info = span(node);
  if (!info) return undefined;
  const id = key(info);
  if (!definitions.has(id)) {
    if (factCount >= MAX_FACTS) { coverage.facts_truncated++; return undefined; }
    const row = { ...info, key: id, name, kind: kindNames[node.kind] || 'Declaration' };
    definitions.set(id, row); add('symbols', row);
  }
  return id;
}
try {
  const snapshot = api.updateSnapshot({ openProjects: [ROOT + 'tsconfig.json'] });
  const project = snapshot.getProjects()[0];
  if (!project) throw new Error('Synthetic project unavailable');
  const program = project.program;
  const checker = project.checker;
  coverage.parse_errors = program.getSyntacticDiagnostics().length;
  for (const [path] of sources) {
    const file = program.getSourceFile(path);
    if (!file) continue;
    coverage.files_analyzed++;
    const stack = [file];
    while (stack.length && coverage.nodes_visited < MAX_NODES) {
      const node = stack.pop(); coverage.nodes_visited++;
      if (declarationKinds.has(node.kind) && node.name && node.name.kind === K.Identifier)
        define(node, node.name.getText(file));
      if (node.kind === K.CallExpression || node.kind === K.NewExpression) {
        const expression = node.expression;
        const dynamic = ![K.Identifier, K.PropertyAccessExpression].includes(expression.kind);
        pending.push({ group: 'calls', node: expression,
          row: { ...span(node), callee: expression.getText(file).slice(0, 512) }, dynamic });
      }
      if (node.kind === K.ImportDeclaration || node.kind === K.ExportDeclaration) {
        const module = node.moduleSpecifier?.text;
        if (typeof module === 'string') {
          const bindings = node.importClause?.namedBindings;
          const elements = bindings?.elements || node.exportClause?.elements || [];
          const imports = [];
          if (node.importClause?.name) imports.push([node.importClause.name, 'default']);
          if (bindings?.name) imports.push([bindings.name, '*']);
          if (node.exportClause?.name) imports.push([node.exportClause.name, '*']);
          for (const element of elements) imports.push([element.name, element.propertyName?.text || element.name.text]);
          if (!imports.length) add('imports', { ...span(node), module, imported: '*', local: '', resolution: 'unresolved' });
          for (const [name, imported] of imports) pending.push({ group: 'imports', node: name,
            row: { ...span(node), module, imported, local: name.text }, dynamic: false });
        }
      }
      if (node.kind === K.Identifier && !(node.parent?.name === node && declarationKinds.has(node.parent.kind)))
        pending.push({ group: 'references', node, row: { ...span(node), name: node.text }, dynamic: false });
      node.forEachChild(child => { stack.push(child); });
    }
    if (stack.length) coverage.facts_truncated++;
  }
  const resolutionCache = new Map();
  function resolve(symbol) {
    if (!symbol || checker.isUnknownSymbol(symbol)) return { resolution: 'unresolved' };
    if (resolutionCache.has(symbol.id)) return resolutionCache.get(symbol.id);
    const original = symbol;
    if (symbol.flags & SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
    if (!symbol || checker.isUnknownSymbol(symbol)) return { resolution: 'unresolved' };
    const targets = [];
    for (const handle of symbol.declarations) {
      const declaration = handle.resolve();
      if (!declaration || !span(declaration)) continue;
      const target = define(declaration, declaration.name?.getText() || symbol.name);
      if (target && !targets.includes(target)) targets.push(target);
    }
    const result = targets.length === 1 ? { resolution: 'declaration', target: targets[0] }
      : { resolution: targets.length ? 'ambiguous' : 'unresolved' };
    resolutionCache.set(original.id, result);
    return result;
  }
  for (let i = 0; i < pending.length && factCount < MAX_FACTS; i += 256) {
    const batch = pending.slice(i, i + 256);
    const symbols = checker.getSymbolAtLocation(batch.map(item => item.node));
    batch.forEach((item, index) => add(item.group, { ...item.row,
      ...(item.dynamic ? { resolution: 'dynamic' } : resolve(symbols[index])) }));
  }
  if (pending.length + definitions.size > MAX_FACTS) coverage.facts_truncated++;
  const output = JSON.stringify({ version: 1, ...rows, coverage,
    parser: { name: 'typescript-native', version: '7.0.2', bridge: 1 },
    limitations: ['Declaration links are static and do not guarantee runtime dispatch.',
      'External packages, computed or dynamic references, standard libraries and workspace compiler options are not loaded.'] });
  if (Buffer.byteLength(output) > 8 * 1024 * 1024) throw new Error('Output limit exceeded');
  process.stdout.write(output);
} finally { api.close(); }
