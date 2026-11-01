export function secondsToFrame(value,fps){
 const text=String(value??'').trim().replace(/[٠-٩]/g,d=>'٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/[۰-۹]/g,d=>'۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace('٫','.');
 if(!/^\d+(?:\.\d+)?$/.test(text)||!Number.isInteger(fps)||fps<1||fps>120)throw Error('اكتب توقيتًا صحيحًا بالثواني');
 const n=Number(text),frame=Math.round(n*fps);if(!Number.isFinite(n)||!Number.isSafeInteger(frame))throw Error('التوقيت خارج النطاق');return frame;
}
