const fs=require('fs');
const path=require('path');
const out=path.resolve('runtime','ui-proof');
fs.mkdirSync(out,{recursive:true});
const table={generated_at_ms:Date.now(),source:'analysis-only detector batch A bootstrap',detectors:{CONFLUENCE:{n:0,label:'n<30',outcome_rate:null,note:'Detector added live; historical replay outcome labelling not backfilled yet.'}}};
fs.writeFileSync(path.join(out,'detector-base-rates.json'),JSON.stringify(table,null,2));
console.log(JSON.stringify(table,null,2));
