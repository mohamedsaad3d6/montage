import sys,tempfile,wave,array,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from repair_preview import build
from cutplan import splice
class RepairPreview(unittest.TestCase):
 def test_nearby_second_deletion_is_also_absent_from_the_first_join_audition(self):
  rate=16000;fps=24;samples=array.array('h',((i*13)%20001-10000 for i in range(4*rate)));cuts=[{'start_frame':24,'end_frame':36,'kind':'reviewed_retake'},{'start_frame':48,'end_frame':60,'kind':'quiet_gap_only'}];t={'duration_frames':96,'tracks':[]};mapping=splice(t,cuts)['raw_to_output']
  with tempfile.TemporaryDirectory()as td:
   result=build(samples,rate,fps,mapping,cuts,Path(td));self.assertEqual([r['join_output_frame']for r in result],[24,36]);self.assertTrue(all(r['context_clock']=='edited_candidate'for r in result))
   for r in result:
    with wave.open(str(Path(td)/r['file']),'rb')as f:self.assertEqual(f.getnframes(),3*rate);pcm=array.array('h',f.readframes(f.getnframes()))
    # Interior audio at 1.25s must come from raw 1.75s, then at1.75s from raw2.75s.
    # A per-cut-only preview incorrectly leaves the second deletion audible.
    for output,source in [(1.25,1.75),(1.75,2.75)]:
     a=round(output*rate);b=round(source*rate);self.assertEqual(pcm[a:a+512],samples[b:b+512])
 def test_adjacent_cuts_share_the_correct_join_and_edge_cuts_do_not_create_empty_audio(self):
  t={'duration_frames':96,'tracks':[]};cuts=[{'start_frame':0,'end_frame':12,'kind':'reviewed_retake'},{'start_frame':24,'end_frame':36,'kind':'quiet_gap_only'},{'start_frame':36,'end_frame':48,'kind':'quiet_gap_only'},{'start_frame':84,'end_frame':96,'kind':'quiet_gap_only'}]
  with tempfile.TemporaryDirectory()as td:
   result=build(array.array('h',[100]*64000),16000,24,splice(t,cuts)['raw_to_output'],cuts,Path(td));self.assertEqual([r['join_output_frame']for r in result],[0,12,12,48]);self.assertTrue(all(r['duration']>0 for r in result));self.assertEqual(result[-1]['join_seconds'],result[-1]['duration'])
