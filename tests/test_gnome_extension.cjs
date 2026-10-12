// Executes the GNOME extension class under a minimal GNOME Shell API simulation.
const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const path=require('path');
const source=path.join(__dirname,'../extension/faco-resource-watch@faco.local/extension.js');
let installed=null, removedTimer=false, launched=null, data=null, action=null;
class Box {constructor(){this.children=[];}add_child(x){this.children.push(x)}}
class Label {constructor(opts){this.text=opts.text;}set_text(v){this.text=v;}}
class Button {
  constructor(o){this.child=o.child;this.events={};this.destroyed=false;}
  connect(kind,fn){this.events[kind]=fn;return 5;}
  disconnect(id){assert.equal(id,5);this.events={};}
  destroy(){this.destroyed=true;}
}
const St={BoxLayout:Box,Label,Button};
const Main={panel:{_centerBox:{insert_child_at_index(button,index){installed={button,index}}}},notify(){}};
const Gio={
  File:{new_for_path(p){return{load_contents(){if(!data)throw Error('No sample');return [true,new TextEncoder().encode(JSON.stringify(data))];}}}},
  Subprocess:{new(args){launched=args;}},SubprocessFlags:{NONE:0},
};
const GLib={PRIORITY_DEFAULT:0,SOURCE_CONTINUE:true,
  timeout_add_seconds(prio,s,fn){assert.equal(s,1);action=fn;return 21;},
  Source:{remove(x){assert.equal(x,21);removedTimer=true;}},
  getenv(){return '/run/user/1000';},
  get_user_runtime_dir(){return '/run/user/1000'},
  get_home_dir(){return '/home/example';},
  build_filenamev(parts){return parts.join('/')},
  FileTest:{EXISTS:1},file_test(){return true},
};
let code=fs.readFileSync(source,'utf8').replace(/^import .+?;\s*$/gm,'').replace('export default class FACOResourceWatch','class FACOResourceWatch');
code+='\nthis.FACOResourceWatch = FACOResourceWatch;';
const env={St,Main,Gio,GLib,Extension:class {},TextDecoder,TextEncoder,Date,JSON,Number,Math,Error};
vm.createContext(env);vm.runInContext(code,env);
const ext=new env.FACOResourceWatch();
const ts=Math.floor(Date.now()/1000);
data={ts,cpu_percent:28,cpu_temp_c:56,ram:{percent:55},gpus:[{
  index:0,percent:87,temp_c:62,vram_used_bytes:4*2**30,vram_total_bytes:16*2**30
}]};
ext.enable();
assert.equal(installed.index,0,'indicator must be before clock');
assert.match(ext._label.text,/CPU 28% 56° RAM 55% GPU 87% 62° VRAM 4.0G\/16.0G/);
installed.button.events.clicked();
assert.equal(launched[0],'/home/example/.local/bin/faco-resource-watch');
assert.equal(launched[1],'open');
data.ts=ts-30;action();assert.equal(ext._label.text,'FACO: OFFLINE');
data=null;action();assert.equal(ext._label.text,'FACO: STARTING…');
const button=ext._button;ext.disable();
assert.equal(removedTimer,true);assert.equal(button.destroyed,true);
console.log('GNOME panel simulation PASSED: left-of-clock insertion, metrics, stale/missing data, click-to-open, timer cleanup.');
