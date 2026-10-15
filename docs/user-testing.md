# User testing kit: UAT-1 and real-device checks (Phase 6, Gate G4)

Gate G4 for the prototype: **at least 80% task success and no open S1/S2 defect** with 8–12
retail investors (SDLC & Master Test Plan §7.7). Run it on the deployed site after the smoke
test in [deploy.md](deploy.md) passes.

## Plan

| | |
|---|---|
| Participants | 8–12 people who invest or plan to (ideally the Phase 1 interviewees); at least 3 who have never seen MarketMood |
| Format | 30-minute sessions: 5 watched live (in person or screen share), the rest remote with this task sheet |
| Devices | each person's own phone if possible; note the phone and browser |
| Roles | one moderator (reads the script, does not help), one note-taker |
| Before | wake the API (Actions → Demo warm-up); check the dashboard shows today's data |

Privacy: record no names, phone numbers or screen recordings. Give each person a code (P01,
P02 …) and write only age band and investing experience. Delete any notes that identify a
person after the report is written.

## Moderator script

> "Thanks for helping. We are testing the website, not you, so nothing you do is wrong.
> Please think aloud: say what you are looking for and what you expect. I will not help
> during the tasks; if you get stuck, say so and we move on. The site is educational and does
> not give investment advice. We do not record your name. Shall we start?"

Open the site on the participant's phone. Read each task exactly as written. Start a timer
when you finish reading; stop it when they answer or give up (2-minute limit per task).

## Tasks

| # | Task (read aloud) | Success when | Test case |
|---|---|---|---|
| T1 | "What mood is the Indian market in today, and how sure is the website about it?" | names the regime and the confidence (or says "very sure / 99%") within 10 s of the page showing data | TC-UAT-01 |
| T2 | "Why does the website think so?" | points to or reads at least one of the three signals in "What's driving this" | TC-UAT-02 |
| T3 | "Ask the AI analyst one question you would really want answered about the market." | types a question and reads the answer without help | TC-UAT-02 |
| T4 | "Find out what happened to the market the last time it was in this mood or in a crisis." | uses a suggested question, the chat or the chart/table to find a past period | |

Record for every task: success (yes / with difficulty / no), time in seconds, and every point
of confusion in the person's own words.

## After the tasks (5 minutes)

1. "In one sentence, what is this website for?"
2. "What was confusing or hard to trust?"
3. "What would you change first?"
4. "Would you use this again? How often?"
5. "Would you pay for a version with alerts and deeper analysis? If yes, roughly how much per
   month feels fair?" (pricing input for Phase 7; not part of the gate)
6. Note the questions they asked the AI in T3: they show which suggested questions to offer.

## Severity of findings

| Level | Meaning | Example | Gate |
|---|---|---|---|
| S1 | blocks a task or misleads about money | wrong regime shown; AI gives buy/sell advice | must be fixed before M1 |
| S2 | task done only with great difficulty | cannot find the chat on a phone | must be fixed before M1 |
| S3 | annoying but workable | unclear label, slow wake-up | backlog |
| S4 | cosmetic | spacing, wording | backlog |

## Results sheet (copy one row per participant)

| Code | Phone / browser | Experience | T1 | T1 s | T2 | T3 | T4 | Question asked in T3 | Confusion points | Pay? |
|---|---|---|---|---|---|---|---|---|---|---|
| P01 | | | | | | | | | | |

Summary for the Test Summary Report: task success per task and overall (successes ÷
attempts), TC-UAT-01 (how many of the participants passed T1 in under 10 s; target 8 of 12),
TC-UAT-02 (T2 and T3 unaided; target ≥ 80%), list of S1/S2 findings with their fixes, the top 3
improvements and the most common real questions.

## Real-device check (Member 1, before the sessions)

One low-end Android phone (Chrome) and one iPhone (Safari), on mobile data, not Wi-Fi.

| Check | Android | iPhone |
|---|---|---|
| Dashboard loads; regime card, brief, signals, chart and tiles visible | | |
| No sideways scrolling anywhere; text readable without zooming | | |
| Chart: 60D / 1Y / 5Y / Max work; the regime colours show separate stretches | | |
| Chat: a suggested question streams; Stop works; thumbs up/down work | | |
| Typing a question: the keyboard does not hide the Ask button | | |
| "How it works" page opens and scrolls; tables scroll sideways inside their box | | |
| Screen reader (TalkBack / VoiceOver): the regime name and the chat answers are read out | | |
| Dark surroundings: nothing hard to read; no layout jump while the page loads | | |
| After 15+ idle minutes: "Waking up the server…" appears, then the data | | |

Write the phone model, OS and browser versions, and file any S1/S2 as a GitHub issue.
