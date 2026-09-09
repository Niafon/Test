import { convertFileSrc, invoke } from '@tauri-apps/api/core'
export const isTauri=()=>typeof window!=='undefined' && '__TAURI_INTERNALS__' in window
export async function openExternal(target:string){if(isTauri()){const{open}=await import('@tauri-apps/plugin-shell');return open(target)}window.open(target,'_blank','noopener,noreferrer')}
export async function pickFolder(){if(!isTauri())return prompt('Folder path')||null;const{open}=await import('@tauri-apps/plugin-dialog');const p=await open({directory:true,multiple:false});return typeof p==='string'?p:null}
export async function pickImages(){if(!isTauri())return[];const{open}=await import('@tauri-apps/plugin-dialog');const p=await open({multiple:true,filters:[{name:'Images',extensions:['png','jpg','jpeg','webp','gif']} ]});return Array.isArray(p)?p:p?[p]:[]}
export function assetUrl(path:string){if(!isTauri())return path;try{return convertFileSrc(path)}catch{return path}}
export async function detachBlock(id:string,x:number,y:number){if(!isTauri())return false;await invoke('spawn_detached_block',{id,x:Math.round(x),y:Math.round(y)});return true}
export async function requestDock(id:string){if(!isTauri())return;await invoke('request_dock',{id})}
export async function showMain(){if(!isTauri())return;await invoke('show_main')}
export async function minimizeMain(){if(!isTauri())return;const{getCurrentWindow}=await import('@tauri-apps/api/window');await getCurrentWindow().minimize()}
export async function closeMainToTray(){if(!isTauri())return;const{getCurrentWindow}=await import('@tauri-apps/api/window');await getCurrentWindow().hide()}
export async function setAutostart(enabled:boolean){if(!isTauri())return false;const p=await import('@tauri-apps/plugin-autostart');enabled?await p.enable():await p.disable();return p.isEnabled()}
export async function setupQuickCaptureHotkey(shortcut:string,onTrigger:()=>void){if(!isTauri())return()=>{};const p=await import('@tauri-apps/plugin-global-shortcut');await p.unregisterAll();await p.register(shortcut,async(e:any)=>{if(!e.state||e.state==='Pressed'){await showMain();onTrigger()}});return()=>{void p.unregisterAll()}}
