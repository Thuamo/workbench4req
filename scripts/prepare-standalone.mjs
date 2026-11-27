import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const frontend=process.cwd();
await fs.cp(path.join(frontend,'.next','static'),path.join(frontend,'.next','standalone','.next','static'),{recursive:true});
try {await fs.cp(path.join(frontend,'public'),path.join(frontend,'.next','standalone','public'),{recursive:true});}catch(error){if(error.code!=='ENOENT')throw error;}
