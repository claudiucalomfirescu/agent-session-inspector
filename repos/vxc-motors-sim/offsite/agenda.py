"""The off-site agenda: segments, the instruction each speaker gets, and the output formats games use.

Kept apart from the runner so a new agenda (a different meeting, a different company) only edits this file.
Each segment is a list of steps; the runner (offsite/run.py) walks them in order. Step kinds:

  say        one speaker posts one message (speaker may be "moderator", a staff id, or "@gm")
  round      every attendee in `order` posts once, with the same instruction
  pick       the moderator chooses who speaks next (NEXT: line); the runner then runs `then` for each pick
  note       a scene line from the runner itself (no LLM call), e.g. "Lunch break"
  tally      the runner scores a game or vote and posts the result as a scene line (no LLM call)
"""

GM = "victor-hale"

SETTING = """Setting: Saturday 31 October 2026, the annual all-staff off-site of VXC Motors, held at The Old Mill,
a countryside hotel near Stratford-upon-Avon. All 12 staff are present, plus Hannah Brooks, the external
facilitator. The whole meeting happens in one group chat room on everyone's laptop, so every contribution is
a chat message: usually 1 to 4 sentences, conversational, first names, an emoji now and then if it suits you.
No headings, no bullet lists unless you are asked for a list, no stage directions in brackets.
Only write your own message: never write lines for other people."""

SEGMENTS = [
    {"id": "welcome", "title": "Welcome", "steps": [
        {"kind": "say", "speaker": "moderator", "instruction":
            "Open the off-site. Welcome everyone, introduce yourself in one line, and give the agenda in one "
            "line: icebreaker game, Victor's business review with Q&A, a brainstorm with voting, a story game "
            "after lunch, and commitments to close. Then hand over to Victor for a short welcome. End with NEXT: victor-hale"},
        {"kind": "say", "speaker": "@gm", "instruction":
            "Give a short, warm welcome as General Manager (2-3 sentences). Thank people for a hard year and say "
            "what you hope today achieves. Do not start the business review yet."},
    ]},
    {"id": "icebreaker", "title": "Icebreaker: two truths and a lie", "steps": [
        {"kind": "say", "speaker": "moderator", "instruction":
            "Explain the icebreaker 'two truths and a lie'. Each person, in turn, first guesses which of the "
            "previous person's three statements is the lie, then posts three statements about themselves, "
            "two true and one invented. Say the scores will be revealed at the end. The order is: {order_names}."},
        {"kind": "round", "game": "two_truths", "instruction":
            "Your turn in 'two truths and a lie'. {guess_part}Then give three short statements about yourself: two true "
            "(from your real life and history) and one plausible lie. Keep it playful and in character.\n"
            "Answer in EXACTLY this format, nothing before or after:\n"
            "{guess_format}1. <statement>\n2. <statement>\n3. <statement>\nLIE: <1, 2 or 3>   (this line is hidden from the others)"},
        {"kind": "tally", "game": "two_truths"},
        {"kind": "say", "speaker": "moderator", "instruction":
            "React to the icebreaker results shown in the last scene line (who fooled the most people, who was "
            "the best detective) in 2-3 sentences, then hand over to Victor for the business review. End with NEXT: victor-hale"},
    ]},
    {"id": "review", "title": "Business review", "steps": [
        {"kind": "say", "speaker": "@gm", "facts": True, "instruction":
            "Present part 1 of the business review: SALES. Use only the figures in the FACT SHEET (units, by "
            "month, by salesperson, discounts, lead sources and lost reasons). 4-6 sentences. Be honest about "
            "what is off-plan. Name people when you praise them."},
        {"kind": "say", "speaker": "@gm", "facts": True, "instruction":
            "Present part 2: AFTERSALES and FINANCE. Use only the FACT SHEET (job cards, warranty share, "
            "technicians, invoiced revenue, unpaid invoices). 3-5 sentences."},
        {"kind": "say", "speaker": "@gm", "facts": True, "instruction":
            "Present part 3: the outlook and your three priorities for the next 12 months (your own judgment, "
            "informed by the fact sheet and BMW's move towards an agency model and EVs). 3-5 sentences. Invite questions."},
        {"kind": "pick", "count": 4, "instruction":
            "Open the Q&A. Choose four people to ask Victor a question, mixing departments and including at "
            "least one person who has not spoken much. Say who goes first. End with NEXT: followed by their four staff ids in order.",
         "then": [
            {"kind": "say", "speaker": "$pick", "instruction":
                "Ask Victor one honest question about the business review, from your role's point of view. "
                "One or two sentences."},
            {"kind": "say", "speaker": "@gm", "facts": True, "instruction":
                "Answer {asker}'s question directly and briefly (2-4 sentences). Use the fact sheet where it helps; "
                "if you do not know, say who will find out."},
        ]},
    ]},
    {"id": "brainstorm", "title": "Brainstorm and vote", "steps": [
        {"kind": "say", "speaker": "moderator", "instruction":
            "Start the brainstorm. The question: 'What is one idea that would make VXC Motors the dealership "
            "customers and staff love most by next October?' Everyone posts exactly one idea, with a short title. "
            "Encourage bold ideas from every department. Say the order is: {order_names}."},
        {"kind": "round", "game": "ideas", "instruction":
            "Post your one idea for the brainstorm, building on the business review and your own job. You may "
            "build on someone else's idea, but make it yours. Answer in EXACTLY this format:\n"
            "IDEA: <title of 3-7 words>\n<one or two sentences: what it is and why it matters>"},
        {"kind": "tally", "game": "ideas"},
        {"kind": "say", "speaker": "moderator", "instruction":
            "Comment in 2-3 sentences on the themes you see in the numbered idea list (last scene line), then "
            "explain the vote: everyone votes for two ideas that are not their own, by number."},
        {"kind": "round", "game": "votes", "instruction":
            "Vote for the two ideas you like best from the numbered list, not your own. Answer in EXACTLY this format:\n"
            "VOTES: <number>, <number>\n<one sentence on why>"},
        {"kind": "tally", "game": "votes"},
        {"kind": "say", "speaker": "moderator", "instruction":
            "Announce the top three ideas from the vote result (last scene line) with their authors, and ask "
            "Victor to say in one message whether he will back them. End with NEXT: victor-hale"},
        {"kind": "say", "speaker": "@gm", "instruction":
            "React to the three winning ideas: for each, say yes, no or 'yes if', and who should own it. 3-5 sentences."},
    ]},
    {"id": "lunch", "title": "Lunch", "steps": [
        {"kind": "note", "text": "Lunch break at The Old Mill. The chat goes quiet for an hour."},
    ]},
    {"id": "story", "title": "Story game: a customer's perfect day", "steps": [
        {"kind": "say", "speaker": "moderator", "instruction":
            "Welcome everyone back and launch the story game 'A customer's perfect day at VXC Motors in 2027'. "
            "Each person adds exactly ONE sentence that continues the story from the last sentence, ideally "
            "showing how their own job makes the day great. The order is: {order_names}. Give the opening "
            "sentence yourself: a customer called Sam wakes up and remembers their BMW's service is today."},
        {"kind": "round", "game": "story", "instruction":
            "Add exactly ONE sentence to the story, continuing from the last sentence, ideally showing your own "
            "job in action. Write only the sentence."},
        {"kind": "say", "speaker": "moderator", "instruction":
            "Close the story with a final sentence and one line on what the story shows about how the teams depend on each other."},
    ]},
    {"id": "commitments", "title": "Commitments and shout-outs", "steps": [
        {"kind": "say", "speaker": "moderator", "instruction":
            "Launch the last round: each person posts one concrete commitment for the next quarter (linked to "
            "today's ideas if possible) and a thank-you shout-out to one colleague from another team. Order: {order_names}."},
        {"kind": "round", "game": "commitments", "instruction":
            "Post your commitment for next quarter and a shout-out to a colleague from another team. Answer as:\n"
            "COMMIT: <one concrete commitment>\nTHANKS: <first name> <for what>"},
        {"kind": "say", "speaker": "@gm", "instruction":
            "Close the off-site as General Manager: 3-5 sentences, mention one or two things people said today by "
            "name, and the one thing you will personally do next week."},
        {"kind": "say", "speaker": "moderator", "instruction":
            "Close the session: thank everyone, one-line summary of the day (icebreaker winner, top idea, story), "
            "and wish them a good evening."},
    ]},
]
