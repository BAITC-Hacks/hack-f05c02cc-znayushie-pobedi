import {test} from 'node:test';
import assert from 'node:assert/strict';
import {confirmAdd,rating,analogs,findProducts,products} from '../src/core.js';
test('cart is unchanged without explicit confirmation',()=>{const cart={};assert.throws(()=>confirmAdd(cart,products[0],2,false),/confirmation_required/);assert.deepEqual(cart,{});});
test('confirmed addition creates a new cart and counts existing quantity',()=>{const cart={'DEMO-101':2};assert.deepEqual(confirmAdd(cart,products[0],3,true),{'DEMO-101':5});assert.equal(cart['DEMO-101'],2);assert.throws(()=>confirmAdd(cart,products[0],47,true),/insufficient_stock/);});
test('sold out, fractional, negative, NaN quantities are rejected',()=>{assert.throws(()=>confirmAdd({},products[2],1,true),/insufficient_stock/);for(const n of [0,-1,1.2,NaN,Infinity])assert.throws(()=>confirmAdd({},products[0],n,true),/invalid_quantity/);});
test('reviews fall back to 30 days, never include future or stale records',()=>{const result=rating([{date:'2026-09-22',score:4},{date:'2026-09-21',score:5},{date:'2026-08-01',score:1},{date:'2026-09-24',score:1}], '2026-09-23');assert.equal(result.score,4.5);assert.equal(result.count,2);assert.equal(result.period,'30days');});
test('today takes priority; missing reviews do not invent quality',()=>{assert.equal(rating([{date:'2026-09-23',score:3},{date:'2026-09-22',score:5}],'2026-09-23').score,3);assert.equal(rating([]).score,null);});
test('analogs retain rating and pole compatibility and exclude unavailable products',()=>{assert.deepEqual(analogs(products[2],products).map(p=>p.id),['DEMO-101','DEMO-102']);assert.equal(analogs(products[4],products).length,0);});
test('search recognizes SKU, Cyrillic C, budget and languages',()=>{assert.equal(findProducts('DEMO-103',products)[0].stock,0);assert.deepEqual(findProducts('автомат С16 до 3000',products).map(p=>p.id),['DEMO-101','DEMO-103']);assert.equal(findProducts('cable',products)[0].id,'DEMO-201');assert.equal(findProducts('шам',products).length,2);});

