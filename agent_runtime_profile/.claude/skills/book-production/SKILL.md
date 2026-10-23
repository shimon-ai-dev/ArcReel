---
name: book-production
description: 制作或编辑有声书和图声书，管理完整原文、角色声音、独立表演、停顿、音效、原分镜图同步和导出。只适用于 output_mode 为 audiobook 或 illustrated_audiobook 的项目。
---

# 书籍制作

先读 get_workflow_plan。章节、剧本、资产、图声书分镜图继续使用原有工具和审阅流程。只有声音与导出经 mcp__arcreel__book_project，不直接写 book/book.json。

- status：读取文档、能力、覆盖、实际音频时间线和 revision。
- sync_episode：传当前原有 episode 集号，从已审阅原剧本同步全部原文、book_speech 表演标注、book_sound_cues 场景音意图及原分镜图。不会另建章节/关键帧工作流。缺书籍文档也从此开始，不用 import_source 绕过原章节。说话人不确定时保持 speaker_confirmed=false。
- save_document：用当前 revision 保存持久 voices、独立 performance、pause_after_seconds、pronunciation、effects 和 keyframes。不得伪造音频版本/任务状态。相同角色跨章节复用同一声音。
- 原文修改必须在原章节/剧本中进行，再 sync_episode；不要在投影音频文档建立第二份原文真相。
- generate：补齐缺失/过期语音，可用 segment_ids 缩小范围，force=true 明确重做。不静默换模型或声音，不丢弃不支持的控制。task_ids 只表示受理，等待真实结果并试听。
- 图声书图片用原 generate-storyboard 流程生成，沿用原资产参考与风格；再 sync_episode 更新图片锚点，不调用独立 keyframe 生成。
- export：WAV/MP3 章节与整本音频；图声书同时生成 manifest 与 HTML 播放包。仅当前 status.complete 为真才算完成。

情绪与风格只写 performance，不进入正文；VOX 的呼吸、哭笑和拉长音需求写 style 自然语言意图，nonverbal 保持 null，除非所选适配器明确声明支持独立非语言事件。发音映射保留原文关系，停顿由程序插入静音。效果、环境、音乐分轨，音效记录来源；非原生发声素材须说明声音一致性限制。音频时长变化后重算锚定事件并重新导出。

audiobook 不配置/查询图像和视频；图声书不需要视频模型、视频能力、视频主轨或 MP4。缺少模型时报告已验证与未验证项，不能把单元测试和文本覆盖当成真实语音质量验收。
