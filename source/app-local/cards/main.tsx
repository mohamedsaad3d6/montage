import React,{useEffect,useState} from 'react';
import {Composition,registerRoot,staticFile,delayRender,continueRender} from 'remotion';
function Card(p:any){const [ready]=useState(()=>delayRender('Arabic font'));
useEffect(()=>{const font=new FontFace('Cairo',`url(${staticFile('Cairo.ttf')})`);font.load().then(f=>{document.fonts.add(f);continueRender(ready)})},[ready]);
return <div dir="rtl" style={{width:p.width,height:p.height,boxSizing:'border-box',background:'rgba(16,40,59,.92)',borderBottom:'4px solid #E6BA72',padding:'12px 28px',display:'flex',alignItems:'center',justifyContent:'flex-start',fontFamily:'Cairo',fontSize:p.fontSize,lineHeight:1.5,fontWeight:700,color:'white',textAlign:'right',overflow:'hidden'}}>{p.text}</div>}
const Root=()=> <Composition id="Card" component={Card} width={1920} height={180} durationInFrames={1} fps={24} calculateMetadata={({props}:any)=>({width:props.width,height:props.height})}/>;
registerRoot(Root);
