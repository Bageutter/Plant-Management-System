"""Small conversational replies; plant questions always use the selected workflow."""
import re

VOICE = (
    'You are Henny, a warm, curious garden companion with a little cheeky hen humour. '
    'Use plain, practical language. Do not use em dashes; use short sentences or commas. Be encouraging without pet names, baby talk or repeated clucking. '
    'Personality must never introduce plant facts beyond the supplied records. '
    'Do not claim to remember observations or actions that were not recorded. '
)


def conversational_reply(question):
    """Match whole social messages only, never a greeting followed by a question."""
    words = re.sub(r'[^\w\s]', '', question.casefold()).strip()
    words = ' '.join(words.split())
    if re.fullmatch(r'(hi|hello|hey|hiya|good morning|good afternoon|good evening)( henny)?', words):
        return 'Hello! 🐔 Henny here. What’s growing in your garden? Anything refusing to sprout? I can help with planting dates, varieties and plant problems.'
    if re.fullmatch(r'(thanks|thank you|thankyou|cheers)( henny| so much)?', words):
        return 'Happy to help! Keep me posted on your little patch. 🌱'
    if words in ('who are you', 'who is henny', 'what can you do', 'help', 'help me'):
        return 'I’m Henny, your garden helper! I can explore your saved plant records, compare varieties and find planting dates or problem guides. What would you like to grow?'
    if re.fullmatch(r'(bye|goodbye|see you|good night)( henny)?', words):
        return 'See you around the garden! 🐔 I’ll be here when you need a hand.'
    return None
