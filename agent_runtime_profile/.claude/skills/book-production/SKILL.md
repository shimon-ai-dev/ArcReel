---
name: book-production
description: 制作或编辑有声书和图声书，管理完整原文、角色声音、独立表演、停顿、音效、关键帧和导出。只适用于 output_mode 为 audiobook 或 illustrated_audiobook 的项目。
---

# 书籍制作

先读 get_workflow_plan。所有书籍命令经 mcp__arcreel__book_project，不直接写 book/book.json。

- status：读取文档、能力、覆盖、实际音频时间线和 revision。
- import_source：完整原文保真导入，保留叙述、对白和顺序。默认 speaker_id 是未确认 narrator；根据上下文修正，不确定时保持 speaker_confirmed=false。
- save_document：用当前 revision 保存持久 voices、独立 performance、pause_after_seconds、pronunciation、effects 和 keyframes。不得伪造音频版本/任务状态。相同角色跨章节复用同一声音。
- edit_segment：用户明确改一句原文时传稳定 segment_id 与 text；其他段和事件 ID 不变，源文位置自动更新。
- generate：补齐缺失/过期语音，可用 segment_ids 缩小范围，force=true 明确重做。不静默换模型或声音，不丢弃不支持的控制。task_ids 只表示受理，等待真实结果并试听。
- keyframe：仅图声书，用已保存 keyframe_id 调图像 Provider；参考图可复用角色/场景素材，一图覆盖多段，绑定稳定段而非旧秒数。
- export：WAV/MP3 章节与整本音频；图声书同时生成 manifest 与 HTML 播放包。仅当前 status.complete 为真才算完成。

情绪、风格、喘息等只写 performance，不进入正文；发音映射保留原文关系，停顿由程序插入静音。效果、环境、音乐分轨，音效记录来源；非原生发声素材须说明声音一致性限制。音频时长变化后重算锚定事件并重新导出。

audiobook 不配置/查询图像和视频；图声书不需要视频模型、视频能力、视频主轨或 MP4。缺少模型时报告已验证与未验证项，不能把单元测试和文本覆盖当成真实语音质量验收。
