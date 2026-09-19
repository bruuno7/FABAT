"""Ejecuta el aislamiento del navegador con dos documentos y almacenamiento clonado."""
import shutil
import subprocess
import unittest
from pathlib import Path


class ChatTabsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node requerido para comprobar JS del navegador')
    def test_duplicate_reload_and_lan_fallback(self):
        script = r'''
const vm = require('node:vm'), fs = require('node:fs'), assert = require('node:assert/strict');
const locks = new Set();
let count = 1;
const env = (withLocks=true, type='navigate') => {
  const scope = {window:{}, crypto:{getRandomValues:a=>{a.fill(count++);return a;}},
    navigator:withLocks ? {locks:{request:(key, opts, fn)=>{
      const lock = locks.has(key)?null:{name:key}; if(lock)locks.add(key);
      return Promise.resolve(fn(lock));
    }}} : {}, performance:{getEntriesByType:()=>[{type}]}, sessionStorage:{setItem:()=>{}}};
  vm.createContext(scope); vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), scope);
  return scope.window.mandoChatTab;
};
(async()=>{
  const one = {convs:[{sid:'private-one'}],cur:'one',strikes:[],session:'scene'};
  await env()(one,'store');
  const duplicate = JSON.parse(JSON.stringify(one));
  await env()(duplicate,'store');
  assert.equal(duplicate.convs.length,0); assert.notEqual(duplicate.tabKey,one.tabKey);
  assert.equal(one.convs[0].sid,'private-one');
  locks.delete('mando-chat-tab:'+one.tabKey);
  await env()(one,'store'); assert.equal(one.convs[0].sid,'private-one');
  const lan = JSON.parse(JSON.stringify(one)); await env(false)(lan,'store');
  assert.equal(lan.convs.length,0);
  const reload = JSON.parse(JSON.stringify(one)); await env(false,'reload')(reload,'store');
  assert.equal(reload.convs[0].sid,'private-one');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script, str(Path(__file__).parent/'static/chat-tab.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
