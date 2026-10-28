// Pure JavaScript regression tests; no browser or external package is needed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag;
    this.children = [];
    this.textContent = '';
    this.hidden = false;
    this.attributes = {};
    this.dataset = {};
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  addEventListener() {}
}

function context() {
  const nodes = new Map();
  const document = {
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, new Element());
      return nodes.get(selector);
    },
    querySelectorAll() { return []; },
    createElement: tag => new Element(tag),
    createTextNode: text => ({ textContent: text }),
    body: new Element('body'),
    activeElement: null,
  };
  const sandbox = vm.createContext({ document, URLSearchParams, Intl, console, Date, Map, BigInt, setTimeout, clearTimeout });
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  const boundary = source.indexOf("$('#close-dialog').addEventListener");
  assert.ok(boundary > 0, 'Frontend initialization boundary exists');
  vm.runInContext(source.slice(0, boundary), sandbox);
  return { sandbox, nodes, run: code => vm.runInContext(code, sandbox) };
}

test('money retains cents above Number.MAX_SAFE_INTEGER', () => {
  const { run } = context();
  assert.equal(run("money('9007199254740993.01')"), '9.007.199.254.740.993,01 ₫');
  assert.equal(run("money('1050000.50')"), '1.050.000,5 ₫');
  assert.equal(run('money(null)'), '—');
});

test('Vietnamese and canonical decimal inputs preserve exact intent', () => {
  const { run } = context();
  assert.equal(run("normalizeAmount('1.050.000,50')"), '1050000.50');
  assert.equal(run("normalizeAmount('9007199254740993.01')"), '9007199254740993.01');
  assert.equal(run("normalizeAmount('1.050.000 ₫')"), '1050000');
  assert.throws(() => run("normalizeAmount('1e6')"));
  assert.throws(() => run("normalizeAmount('5.1234')"));
});

test('auction state uses server time and treats the closing boundary as ended', () => {
  const { run, sandbox } = context();
  sandbox.now = Date.now();
  run('app.offset = 0; serverNow = () => now;');
  sandbox.auction = { status: 'OPEN', opens_at: new Date(sandbox.now - 1000).toISOString(), closes_at: new Date(sandbox.now).toISOString() };
  assert.equal(run('currentState(auction)'), 'ENDED');
  sandbox.auction.status = 'CLOSED';
  assert.equal(run('currentState(auction)'), 'CLOSED');
});

test('new filter response wins even when an earlier request finishes last', async () => {
  const { run, nodes } = context();
  run("var pending=[]; api=() => new Promise(resolve => pending.push(resolve)); cardFor=a=>a; updateCountdowns=()=>{};");
  const first = run("app.filters.state='ALL'; loadAuctions();");
  const second = run("app.filters.state='LIVE'; loadAuctions();");
  assert.equal(run('pending.length'), 2);
  run("pending[1]({items:[{id:22,title:'Latest'}]});");
  await second;
  run("pending[0]({items:[{id:11,title:'Old'}]});");
  await first;
  assert.equal(nodes.get('#auction-grid').children[0].id, 22);
  assert.equal(run('app.items[0].id'), 22);
  assert.equal(nodes.get('#auction-grid').attributes['aria-busy'], 'false');
});

test('forced post-transaction refresh supersedes an in-flight poll', async () => {
  const { run, nodes } = context();
  run("var pending=[]; var observed=[]; api=()=>new Promise(resolve=>pending.push(resolve)); updateDetail=d=>observed.push(d.version); app.detailId=7;");
  nodes.set('#auction-dialog', { open: true });
  const old = run('refreshDetail();');
  const fresh = run('refreshDetail(true);');
  run('pending[1]({version:2});');
  await fresh;
  run('pending[0]({version:1});');
  await old;
  assert.equal(run('observed.join()'), '2');
});

test('opening another auction releases the previous polling guard', async () => {
  const { run, nodes } = context();
  run("var pending=[]; var observed=[]; api=()=>new Promise(resolve=>pending.push(resolve)); updateDetail=d=>observed.push(d.version); app.detailId=7; app.detail={auction:{id:7}};");
  nodes.set('#auction-dialog', { open: true });
  const previous = run('refreshDetail();');
  const opening = run('openAuction(8,true);');
  run('pending[1]({version:8});');
  await opening;
  const following = run('refreshDetail();');
  assert.equal(run('pending.length'), 3, 'The new detail must keep receiving updates');
  run('pending[2]({version:9});');
  await following;
  run('pending[0]({version:7});');
  await previous;
  assert.equal(run('observed.join()'), '8,9');
});

test('closing another auction cannot overwrite the currently open form', async () => {
  const { run, nodes } = context();
  run("var finishClose; var feedbackCount=0; api=()=>new Promise(resolve=>finishClose=resolve); updateDetailState=()=>{}; showFormMessage=()=>feedbackCount++; toast=()=>{}; refreshDetail=async()=>{}; loadBootstrap=async()=>{}; loadAuctions=async()=>{}; app.detailId=7; app.detail={auction:{id:7}};");
  nodes.set('#bid-strategy', { value: 'row_lock' });
  nodes.set('#auction-dialog', { open: true });
  const closing = run('closeAuction();');
  run("app.detailId=8; finishClose({status:'CLOSED',code:'AUCTION_CLOSED'});");
  await closing;
  assert.equal(run('feedbackCount'), 0);
  assert.equal(run('app.mutationBusy'), false);
});

test('failed metrics load can be retried when the page is revisited', async () => {
  const { run } = context();
  run("api=async()=>{throw new Error('Offline')};");
  await run('loadMeasurements();');
  assert.equal(run('app.labLoaded'), false);
  assert.equal(run('app.measurementsBusy'), false);
});
