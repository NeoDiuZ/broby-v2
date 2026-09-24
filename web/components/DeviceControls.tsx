'use client';
import {useEffect,useState} from 'react';
import {clearDownloadedSnapshots,deviceInfo,flushDeviceWrites,lockDevice,localAll,offlineShellStatus,legacyDeviceRows} from '@/lib/device';
import {assertDeviceCanLock} from '@/lib/recording';
import {useWorkspace} from '@/lib/workspace';
import {BusyButton} from './ui';
export function DeviceControls(){
 const w=useWorkspace(),info=deviceInfo();const [shell,setShell]=useState(offlineShellStatus()),[queued,setQueued]=useState(0),[legacy,setLegacy]=useState(0);
 useEffect(()=>{const update=()=>setShell(offlineShellStatus());window.addEventListener('broby-shell-status',update);update();return()=>window.removeEventListener('broby-shell-status',update)},[]);
 useEffect(()=>{void legacyDeviceRows().then(setLegacy).catch(()=>{})},[]);
 useEffect(()=>{let cancelled=false;void Promise.all([localAll('pending'),localAll('recordings')]).then(([notes,audio])=>{if(!cancelled)setQueued(notes.length+audio.length)}).catch(()=>{});return()=>{cancelled=true}},[w.pending]);
 return <section className="settings-section" aria-label="Saved device workspace"><h3>Saved device workspace</h3><p>Clinic copies, draft text and queued audio are encrypted on this browser. Reloading asks for your existing account password. Keep that password available while offline.</p><p>{shell}</p>{legacy>0&&<p role="alert" className="error">{legacy} older device records still need migration. Sign into their original clinic accounts while online to encrypt them. Keep this browser data until the old work has synced.</p>}<p>Device access until {info?new Date(info.expiresAt).toLocaleString('en-SG'):'not available'} · {queued} saved note or recording queues.</p><p>A browser cleanup or storage eviction can remove unsynced work. Device storage is not a backup. Online sign-in is required after expiry or sign-out.</p><div className="actions"><BusyButton onClick={async()=>{assertDeviceCanLock();await flushDeviceWrites();localStorage.setItem('broby-lock-signal',crypto.randomUUID());lockDevice()}}>Lock this device</BusyButton><BusyButton onClick={async()=>{await clearDownloadedSnapshots();w.notify('Downloaded clinic copies cleared. Drafts and unsynced audio are retained; this open clinic will be cached again on refresh.')}}>Clear downloaded clinic copies</BusyButton></div></section>
}
