// Lets `node --test tests/ui` work on Node 22, which runs a directory argument as a script.
// Newer and older Node versions walk the directory themselves, so this only loads the test files.
const fs = require('node:fs');
const path = require('node:path');
for (const f of fs.readdirSync(__dirname).filter((n) => n.endsWith('.test.mjs')).sort()) {
  import(path.join(__dirname, f));
}
