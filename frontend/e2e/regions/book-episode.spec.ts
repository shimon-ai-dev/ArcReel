import { test, expect } from "../support/test.ts";
import { recorded, RECORDED_ACCESS_TOKEN } from "../support/recorded.ts";
import type { BookState } from "../../src/types/book.ts";
import { clearAgentOverlay } from "../support/region-helpers.ts";


for (const mode of ["illustrated_audiobook", "audiobook"] as const) {
test(`${mode} uses original studio and chapter audio (synthetic fixture)`, async ({ page, api }, testInfo) => {
  const project = recorded<{project: Record<string, unknown>; scripts: Record<string, {content_mode: string; segments: Record<string, unknown>[]}>}>("project-demo.json");
  project.project.output_mode = mode;
  const script = project.scripts["episode_1.json"];
  if (script.content_mode === "narration") script.segments = [{segment_id:"E1S01",episode:1,duration_seconds:5,segment_break:false,novel_text:"雨夜，他轻声说：别担心，我回来了。",characters_in_segment:[],image_prompt:"写实真人剧，雨夜窗边",video_prompt:"不要显示这个视频提示词"}];
  const book: BookState = {book:{schema_version:1,revision:1,title:"雨夜",original_text:"雨夜，他轻声说：别担心，我回来了。",normalized_text:"雨夜，他轻声说：别担心，我回来了。",chapters:[{id:"chapter-1",episode:1,title:"第一章",segments:[{id:"speech-1",unit_id:"E1S01",text:"别担心，我回来了。",source_start:0,source_end:10,speaker_id:"narrator",speaker_confirmed:true,performance:{emotion:"温柔、安慰",intensity:0.5,emotion_vector:null,style:null,speed:null,nonverbal:null},pause_after_seconds:0.3,pronunciation:[],audio_versions:[],selected_audio_version:null,status:"pending",task_id:null,error:null}]}],voices:{narrator:{id:"narrator",name:"旁白",adapter:"voxcpm2",model:"VoxCPM2",base_url:"http://127.0.0.1:7862",voice:"",reference_audio:null,reference_audio_digest:null,language:"zh",settings:{clone_mode:"controllable"}}},effects:[],keyframes:[]},timeline:null,capabilities:{},status:{complete:false,coverage_valid:true,missing_audio:["speech-1"],missing_images:[]},tasks:[]};
  api.override({"GET /api/v1/projects/demo":{status:200,body:project},"GET /api/v1/projects/demo/book":{status:200,body:book},"GET /api/v1/projects/demo/events/stream":{status:404,body:{}},"POST /api/v1/projects":{status:200,body:{success:true,name:"demo",project:project.project}}});
  await page.addInitScript(token=>localStorage.setItem("arcreel_auth_token",token),RECORDED_ACCESS_TOKEN);
  await page.goto("/app/projects");
  await page.getByRole("button",{name:"新建项目"}).first().click();
  const dialog=page.getByRole("dialog",{name:"新建项目"});
  await dialog.getByRole("combobox",{name:"输出模式"}).click();
  await page.getByRole("option",{name:mode === "audiobook" ? "有声书" : "图声书",exact:true}).click();
  await dialog.getByRole("textbox",{name:"项目标题"}).fill("雨夜");
  await dialog.getByRole("radio",{name:/剧情演绎/}).check({force:true});
  await dialog.getByRole("button",{name:"下一步"}).click();
  await expect(dialog.getByText("视频模型",{exact:true})).toHaveCount(0);
  await page.screenshot({path:testInfo.outputPath("book-shared-wizard.png")});
  if (mode === "illustrated_audiobook") await dialog.getByRole("button",{name:"下一步"}).click();
  await dialog.getByRole("button",{name:"创建项目"}).click();
  await expect(dialog).toHaveCount(0);
  await page.goto("/app/projects/demo/episodes/1");
  await expect(page.getByTestId("workspace-sidebar")).toBeVisible();
  if (testInfo.project.name === "1440x900") {
    await expect(page.getByRole("complementary", { name: "Agent 面板" })).toBeVisible();
  }
  await clearAgentOverlay(page);
  await expect(page.getByRole("tab",{name:"声音",exact:true})).toBeVisible();
  if (mode === "illustrated_audiobook") {
    await expect(page.getByRole("tab", { name: "分镜", exact: true })).toHaveAttribute("aria-selected", "true");
  } else {
    await expect(page.getByRole("tab", { name: "分镜", exact: true })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "声音", exact: true })).toHaveAttribute("aria-selected", "true");
  }
  await expect(page.getByRole("button", { name: /^生成视频/ })).toHaveCount(0);
  await expect(page.getByText("不要显示这个视频提示词",{exact:true})).toHaveCount(0);
  await expect(page.getByRole("tab",{name:"剪辑",exact:true})).toHaveCount(0);
  await page.screenshot({path:testInfo.outputPath("book-original-storyboard.png")});
  await page.getByRole("tab",{name:"声音",exact:true}).click();
  await expect(page.getByText("别担心，我回来了。",{exact:true}).first()).toBeVisible();
  await expect(page.getByRole("button",{name:"同步本章分镜到声音"})).toBeVisible();
  await page.screenshot({path:testInfo.outputPath("book-chapter-audio.png")});
  await page.getByRole("tab",{name:"试听与导出",exact:true}).click();
  await expect(page.getByRole("button",{name:/WAV/})).toBeVisible();
  await page.screenshot({path:testInfo.outputPath("book-listen-export.png")});
  await page.goBack();
  await expect(page.getByRole("tab", { name: "声音", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("button",{name:"同步本章分镜到声音"})).toBeVisible();
});

}
