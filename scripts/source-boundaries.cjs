// Analyze source dependencies using the actual TypeScript path resolver.
const fs = require('node:fs');
const path = require('node:path');
const ts = require('../../hirava-webapp/node_modules/typescript');
const workspace = path.resolve(__dirname, '../..');
function files(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? files(path.join(dir, e.name)) : [path.join(dir,e.name)]);
}
for (const name of ['hirava-webapp']) {
  const root = path.join(workspace, name), src = path.join(root,'src');
  const config = ts.readConfigFile(path.join(root,'tsconfig.json'), ts.sys.readFile);
  const options = ts.parseJsonConfigFileContent(config.config, ts.sys, root).options;
  const all = files(src);
  const entries = all.filter(p => name === 'hirava-webapp'
    ? /(?:page|layout|route|loading|error|not-found|template|proxy)\.tsx?$/.test(p)
    : (p.includes(path.join('app','api')) && /route\.ts$/.test(p)) || p === path.join(src,'proxy.ts'));
  const seen = new Set(), queue = [...entries];
  while (queue.length) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    const source = fs.readFileSync(file,'utf8');
    const imports = ts.preProcessFile(source, true, true).importedFiles;
    for (const item of imports) {
      const resolution = ts.resolveModuleName(item.fileName,file,options,ts.sys).resolvedModule;
      if (resolution && resolution.resolvedFileName.startsWith(src.replaceAll('\\','/'))) queue.push(path.normalize(resolution.resolvedFileName));
      else if (resolution && path.resolve(resolution.resolvedFileName).startsWith(src + path.sep)) queue.push(path.resolve(resolution.resolvedFileName));
    }
  }
  const retained = all.filter(p => seen.has(p)).map(p => path.relative(root,p).replaceAll('\\','/'));
  const orphaned = all.filter(p => /\.[cm]?tsx?$/.test(p) && !seen.has(p)).map(p => path.relative(root,p).replaceAll('\\','/'));
  fs.writeFileSync(path.join(workspace,'hirava-api/test-output',name.replaceAll('/','-')+'-boundary.json'),JSON.stringify({retained,orphaned},null,2));
  console.log(name, 'entry points', entries.length, 'reachable files', retained.length, 'unused source files', orphaned.length);
  console.log('Reachable database adapters:', retained.filter(p=> /(?:prisma\.ts|upload-storage|sync-user|gateway-identity)/.test(p)));
}
