import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BookSegments } from "./BookSegments";
import type { BookDocument, BookSegment } from "@/types/book";
const segment: BookSegment = {id:"one",text:"当前章节台词",source_start:0,source_end:6,speaker_id:"voice",speaker_confirmed:true,performance:{emotion:"温柔",intensity:0.5,emotion_vector:null,style:"轻声",speed:null,nonverbal:null},pause_after_seconds:0,pronunciation:[],audio_versions:[],selected_audio_version:null,status:"pending",task_id:null,error:null};
const book: BookDocument = {schema_version:1,revision:1,title:"测试",original_text:"",normalized_text:"",chapters:[{id:"c1",episode:1,title:"第一章",segments:[segment]},{id:"c2",episode:2,title:"第二章",segments:[{...segment,id:"two",text:"其他章节台词"}]}],voices:{voice:{id:"voice",name:"人物",adapter:"voxcpm2",model:"VoxCPM2",base_url:"",voice:"",reference_audio:null,reference_audio_digest:null,language:"zh",settings:{clone_mode:"controllable"}}},effects:[],keyframes:[]};
describe("original chapter audio editing",()=>{
 it("shows only current chapter and does not offer unsupported VOX knobs",()=>{
 render(<BookSegments project="test" book={book} chapterId="c1" onChange={vi.fn()} disabled={false} generate={vi.fn()} correctText={vi.fn()}/>);
 expect(screen.getByText("当前章节台词")).toBeVisible();
 expect(screen.queryByText("其他章节台词")).not.toBeInTheDocument();
 expect(screen.queryByLabelText("情绪强度")).not.toBeInTheDocument();
 expect(screen.queryByLabelText("非语言发声")).not.toBeInTheDocument();
 });
});
