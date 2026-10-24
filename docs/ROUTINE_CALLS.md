# Hiyo Routine Feedback Calls

Routine 是用户主动设置的例行反馈电话：每天或每周几次、早上或晚上、具体时间。它与发现持续异常时的额外关怀电话分开。

## 通话节奏

统一开场：**“Hi Alex, it's Hiyo, your AI coach. How are you feeling today?”**

先等用户回答。每轮最多一至两句短句、一次一个问题。三种人格共用同一流程，不因“温柔”或“理性”而延长通话。

| 用户回答与情况 | 下一步 |
|---|---|
| Positive | “Okay, sounds good.” → 简短数据总结 → 日程和训练计划 → 一句鼓励 → 收尾 |
| Negative，昨天是否训练未知 | 问“Did you train yesterday?”，不能把缺记录当成没训练 |
| Negative，昨天没训练 | 问原因，再问今天是否想训练；只有时间、动力等障碍且恢复允许时，结合目标直接提醒 |
| 没训练是因为不适或疲劳 | 优先恢复，不用目标逼迫训练 |
| 昨天练了上肢／下肢 | 只询问对应部位的恢复情况，不进行全身长访谈 |
| 很酸，同时睡眠不足、明确疲劳或可靠 stress 读数偏高 | 建议今天休息，下一次训练前再评估；一句安慰后结束 |
| 很酸，但没有上述信息支持直接安排休息日 | 提议避开酸痛部位、减量或休息；知道原计划参数时才提出数值调整 |

常规晨间收尾：**“Have a nice day.”** 晚间使用 **“Have a restful evening.”** 用户主动继续说时可以回应，不能为了走完脚本打断用户。

## Positive：一句有用的总结，然后让用户开始一天

以下均为模拟对话，数值与日程只是示例。

> Hiyo: “Hi Alex, it's Hiyo, your AI coach. How are you feeling today?”
>
> Alex: “Pretty good.”
>
> Hiyo: “Okay, sounds good. Your recorded sleep was eight hours, and recovery is 75%; current stress data isn't available.”
>
> Hiyo: “You have a meeting at ten and upper-body training planned this afternoon. Keep it steady, and have a nice day.”

只有日历已核验时才提及会议；只有训练计划已提供时才提醒具体项目。Positive 不等于所有数据正常：如存在明确偏离，仍用一句话提醒数值及参照，再给出简短关心或分析。

## Negative：昨天没训练

> Hiyo: “How are you feeling today?”
>
> Alex: “Not great. I didn't train yesterday.”
>
> Hiyo: “What got in the way?”
>
> Alex: “Work ran late. Physically, I'm fine.”
>
> Hiyo: “You set a goal of three strength sessions a week. Would you like to make room for one today?”
>
> Alex: “Yes.”
>
> Hiyo: “Let's keep today's planned session manageable. One missed day doesn't undo your effort—have a nice day.”

如果原因是身体不适或疲劳，替换成简短的恢复建议。若用户不想训练，尊重选择，不继续反复劝说。

## Negative：昨天练过，而且很酸

> Hiyo: “How is your lower body feeling after yesterday's session?”
>
> Alex: “My glutes and quads are really sore, and I'm tired.”
>
> Hiyo: “You also recorded six hours of sleep. Let's make today a rest day and reassess before the next session.”
>
> Hiyo: “It's okay to take today a little easier. Have a nice day.”

如有可靠的 stress 数据，可以用明确的数值和时间替换部分总结；不为了加进全部指标而长篇播报。

## 人格只改变关心的方式

三种人格共享事实和建议边界，同样简短。以下是在确认疲劳、酸痛与睡眠不足后的建议示例：

| 人格 | 表达示例 |
|---|---|
| 温柔陪伴型 | “That sounds uncomfortable. With the soreness and short sleep, let's take today to recover.” |
| 清晰行动型 | “Today's suggestion: rest and an earlier wind-down. We'll reassess before the next workout.” |
| 理性解释型 | “The soreness, fatigue, and shorter sleep support easing today's plan. A single score wouldn't tell us that alone.” |

不再对每次负面回答都追加“想倾诉还是解决问题”的长分支；用户需要更多情绪支持时再展开。

## 数据总结要准确

- 睡眠、Recovery、Strain 分别说明，不能用 Strain 或心率冒充 Stress Score。
- Stress 保留来源、分值范围、时间和统计口径。例如“09:15 的 stress snapshot 为 2.4/3”，不能称为“全天平均压力 2.4”。
- 当前 snapshot 默认只接受最近 15 分钟且为当地今天的数据；今日均值也必须明确截至时间。过期、未来或缺失数据不当成当前读数。
- 有充分历史时，区分“本次偏离个人基线”和“连续多天偏离”。一次偏离可在 routine 中提醒，但不会被说成已经持续多日。
- 睡眠少于用户自身目标时，可以准确说明差值；不把目标差值说成疾病。
- 对异常的安慰不等于保证“肯定没事”，分析也不等于诊断。

目前 [WHOOP 官方公开 API 文档](https://developer.whoop.com/api/)列出了 Recovery、Sleep、Strain 等数据，未列出 Stress Score 接口。本实现支持由有权限的数据适配器提供独立的 stress 数据结构，但没有声称已接通 WHOOP stress。缺失时说清楚，不伪造分数。

## 配置与实现

现有 `POST /api/profile` 可设置：

```json
{
  "routine": {
    "enabled": true,
    "frequency": "weekly",
    "calls_per_week": 3,
    "weekdays": [0, 2, 4],
    "time_of_day": "evening",
    "local_time": "20:00"
  }
}
```

周一为 0，周日为 6。只选“每周三次”而未指定日期时，默认周一、三、五；可显式修改。每天选 `frequency: daily`。未指定时间时，早上默认 09:00，晚上默认 20:00，均使用用户时区。

`routine.enabled: false` 或明确设为 null 都会停用 routine，不退回旧晨间拨号。原有晨间功能仅在没有配置新版 routine 时保持兼容。

用户明确预订的 routine 与 Low/Medium/High 额外干预分开：Low 不会取消已经同意的例行电话；routine 仍占用每日电话及花费上限，且必须通过电话同意、静默时间、日历、暂停和去重检查。日历忙到错过用户窗口时不晚几个小时补打。

`POST /api/soul/evaluate` 支持 `event: routine_checkin`，其 `routine_answers` 记录对话已经获得的回答，输出下一阶段、一个问题或收尾、数据事实、日程、训练调整和提示词。它不自行提取实时语音回答，也不直接拨号；通话适配器需要将回答更新到这个结构。

`hiyo/routine_schedule.py` 负责共同的频率和时段判断；`hiyo/soul/routine.py` 负责短对话分支和有来源的数据总结。现有电话执行循环也识别 routine 的每日／每周与早／晚时间设置。

若知道原计划训练时长，原型可提出减少约四分之一的时长作为讨论选项；没有基准时不编造重量、组数或强度百分比。这是待验证的产品启发式，所有训练修改仍需用户同意。
