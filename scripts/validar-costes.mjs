import fs from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {costSnapshot} from './economic-activity.mjs';
const rows=gunzipSync(fs.readFileSync(process.argv[2])).toString('utf8').trim().split('\n').filter(Boolean).map(x=>JSON.parse(x));
const result=costSnapshot(rows,process.argv[3]);
console.log(result.note);
process.exitCode=result.state==='ok'?0:2;
