const {test}=require('node:test');
const fs=require('node:fs');const vm=require('node:vm');
vm.runInThisContext(fs.readFileSync('public_site/search.js','utf8'));
vm.runInThisContext(fs.readFileSync('tests/public-search.cases.js','utf8'));
test('Public search filters',()=>publicSearchCases());
