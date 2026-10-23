import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { BookEvents } from "./BookEvents";
import { bookApi } from "@/api/book";
import type { BookDocument, BookSegment } from "@/types/book";
it("binds a scene-sound intention using its exact id without another chapter's cues",async()=>{
 const segment:BookSegment={id:"s1",text:"台词",source_start:0,source_end:2,speaker_id:"narrator",speaker_confirmed:true,performance:{emotion:null,intensity:1,emotion_vector:null,style:null,speed:null,nonverbal:null},pause_after_seconds:0,pronunciation:[],audio_versions:[],selected_audio_version:null,status:"pending",task_id:null,error:null};
 const book:BookDocument={schema_version:1,revision:1,title:"测试",original_text:"台词",normalized_text:"台词",chapters:[{id:"c1",episode:1,title:"第一章",segments:[segment]}],voices:{},effects:[],keyframes:[],sound_cues:[{id:"rain",episode:1,unit_id:"unit1",segment_id:"s1",end_segment_id:null,description:"屋外雨声",track:"ambience"},{id:"elsewhere",episode:2,unit_id:"unit2",segment_id:"s2",end_segment_id:null,description:"另章音效",track:"sfx"}]};
 vi.spyOn(bookApi,"upload").mockResolvedValue({path:"assets/rain.wav",duration_seconds:4});
 const changed=vi.fn();
 render(<BookEvents project="test" book={book} chapterId="c1" disabled={false} onChange={changed} run={action=>{void action();}}/>);
 expect(screen.queryByText("另章音效")).not.toBeInTheDocument();
 await userEvent.upload(screen.getByLabelText("场景音意图，待绑定音频素材（未生成声音）"),new File(["audio"],"rain.wav",{type:"audio/wav"}));
 await waitFor(()=>expect(changed).toHaveBeenCalledWith(expect.objectContaining({effects:[expect.objectContaining({id:"rain",segment_id:"s1",track:"ambience",path:"assets/rain.wav"})]})));
});
