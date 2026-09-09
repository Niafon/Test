import { useState } from 'react'
import { CornerDownLeft, Sparkles } from 'lucide-react'
import { motion } from 'motion/react'
import { useQuestboard } from '../store'
export function QuickCapture({open,onClose}:{open:boolean,onClose:()=>void}){const[text,setText]=useState('');const add=useQuestboard(s=>s.addQuest);if(!open)return null;const submit=()=>{if(!text.trim())return;add(text.trim());setText('');onClose()};return <div className="capture-backdrop" onMouseDown={onClose}><motion.div className="quick-capture glass-heavy" initial={{opacity:0,scale:.93,y:-20}} animate={{opacity:1,scale:1,y:0}} onMouseDown={e=>e.stopPropagation()}><div className="capture-icon"><Sparkles size={18}/></div><input autoFocus value={text} onChange={e=>setText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')submit();if(e.key==='Escape')onClose()}} placeholder="Новый квест…"/><button onClick={submit}><CornerDownLeft size={16}/></button></motion.div></div>}
