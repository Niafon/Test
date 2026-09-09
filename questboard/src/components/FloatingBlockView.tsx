import { useMemo } from 'react'
import { ArrowDownToLine, GripHorizontal } from 'lucide-react'
import { motion } from 'motion/react'
import { useQuestboard } from '../store'
import { requestDock } from '../platform'
import { BlockContent } from './BlockContent'
export function FloatingBlockView({blockId}:{blockId:string}){const block=useQuestboard(s=>s.blocks.find(b=>b.id===blockId));const fallback=useMemo(()=>({id:blockId,type:'note' as const,title:'Detached block',x:0,y:0,w:2,h:2}),[blockId]);const b=block??fallback;return <main className="floating-window"><motion.div className="floating-card glass-card" initial={{scale:.76,opacity:0,filter:'blur(16px)'}} animate={{scale:1,opacity:1,filter:'blur(0px)'}} transition={{type:'spring',stiffness:340,damping:25}}><div className="floating-titlebar" data-tauri-drag-region><GripHorizontal size={18}/><span>{b.title}</span><button onClick={()=>requestDock(b.id)}><ArrowDownToLine size={15}/> Dock</button></div><div className="floating-body"><BlockContent block={b}/></div></motion.div></main>}
