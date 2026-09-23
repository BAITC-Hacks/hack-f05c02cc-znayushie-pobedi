// Server-side diagnostic only. Never ship Basic Auth credentials to the browser.
import {mkdir,writeFile} from 'node:fs/promises';
const username=process.env.EKT_API_USERNAME,password=process.env.EKT_API_PASSWORD;
if(!username||!password)throw Error('Set EKT_API_USERNAME and EKT_API_PASSWORD in the process environment.');
const page=Number(process.argv[2]||1);
if(!Number.isInteger(page)||page<1)throw Error('Page must be a positive integer.');
const response=await fetch(`https://ekt.kz/api/products?page=${page}`,{headers:{Authorization:'Basic '+Buffer.from(`${username}:${password}`).toString('base64')},signal:AbortSignal.timeout(15000),redirect:'error'});
if(!response.ok)throw Error(`Catalog returned HTTP ${response.status}.`);
const data=await response.json();
await mkdir('data',{recursive:true});
await writeFile(`data/catalog-page-${page}.json`,JSON.stringify({retrievedAt:new Date().toISOString(),source:'ekt.kz',data},null,2));
console.log(`Saved private snapshot: data/catalog-page-${page}.json. Inspect and map the schema before use; prices and stock are not real-time.`);
