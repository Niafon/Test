import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { useQuestboard } from '../store'
import { DetachableBlock } from './DetachableBlock'
import { isTauri } from '../platform'
export function Dashboard(){const blocks=useQuestboard(s=>s.blocks),dock=useQuestboard(s=>s.dockBlock);const[pending,setPending]=useState<string|null>(null)
 useEffect(()=>{if(!isTauri())return;let off:(()=>void)|undefined;import('@tauri-apps/api/event').then(async({listen})=>{off=await listen<{id:string}>('request-dock-block',e=>setPending(e.payload.id))});return()=>off?.()},[])
 const visible=blocks.filter(b=>!b.detached||b.id===pending)
 return <><motion.section className={`dashboard ${pending?'dock-mode':''}`} initial={{opacity:0}} animate={{opacity:1}}>{visible.map(b=><DetachableBlock key={b.id} block={b}/>)}</motion.section>{pending&&<div className="dock-overlay"><div className="dock-banner glass-heavy">Выбери место, куда влить блок обратно</div><div className="dock-grid">{Array.from({length:24},(_,i)=><button key={i} onClick={()=>{dock(pending,i%4,Math.floor(i/4));setPending(null)}}><span>{i%4+1}:{Math.floor(i/4)+1}</span></button>)}</div></div>}</>}
