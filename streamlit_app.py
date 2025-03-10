import streamlit as st
import os
import tempfile
from openai import OpenAI
import guitarpro

def process_guitar_pro(file_path):
    # Parse the GuitarPro file into a Song object
    song = guitarpro.parse(file_path)

    # Extract global metadata from the song
    tempo = song.tempo  # Tempo in BPM

    # Determine key signature (if not present, default to C major)
    try:
        key_info = song.key if hasattr(song, 'key') else song.keySignature
    except AttributeError:
        key_info = None

    key_text = "C"  # default
    if key_info:
        # Try to get number of sharps and mode from key_info
        try:
            sharps, is_minor = key_info[0], key_info[1]
        except Exception as e:
            # If key_info is an object or enum, derive sharps and mode from its value or name
            val = getattr(key_info, 'value', None)
            if val:
                sharps, is_minor = val[0], val[1]
            else:
                name = str(key_info)
                sharps = None
                is_minor = 1 if "Minor" in name else 0
                # Extract root from name if possible (e.g., "KeySignature.GMajor")
                for noteName in ["C","G","D","A","E","B","F#","C#","F","Bb","Eb","Ab","Db","Gb","Cb"]:
                    if noteName in name:
                        key_text = noteName
                        break
        # Map sharps/flats count to key name
        if 'sharps' in locals() and sharps is not None:
            major_map = {0:"C", 1:"G", 2:"D", 3:"A", 4:"E", 5:"B", 6:"F#", 7:"C#",
                         -1:"F", -2:"Bb", -3:"Eb", -4:"Ab", -5:"Db", -6:"Gb", -7:"Cb"}
            minor_map = {0:"Am", 1:"Em", 2:"Bm", 3:"F#m", 4:"C#m", 5:"G#m", 6:"D#m", 7:"A#m",
                         -1:"Dm", -2:"Gm", -3:"Cm", -4:"Fm", -5:"Bbm", -6:"Ebm", -7:"Abm"}
            key_text = minor_map[sharps] if is_minor else major_map[sharps]

    # Get initial time signature (from first measure)
    if song.tracks and song.tracks[0].measures:
        ts = song.tracks[0].measures[0].header.timeSignature
        num = ts.numerator
        den = ts.denominator.value  # denominator is a Duration object (e.g., value=4 for quarter note)
    else:
        num, den = 4, 4  # default 4/4

    # Extract additional song metadata if available
    song_title = getattr(song, 'title', 'Untitled')
    song_artist = getattr(song, 'artist', 'Unknown Artist')
    song_album = getattr(song, 'album', 'Unknown Album')
    song_composer = getattr(song, 'composer', 'Unknown Composer')
    song_copyright = getattr(song, 'copyright', '')
    song_lyrics = getattr(song, 'lyrics', '')
    song_instructions = getattr(song, 'instructions', '')
    song_notice = getattr(song, 'notice', '')
    song_subtitles = getattr(song, 'subtitles', [])

    # Prepare output lines
    output = []
    # Document custom notation in the output for user clarity
    output.append("Custom ABC notation enhancements:")
    output.append("- Chords are labeled in brackets (e.g. [C5] for C power chord)")
    output.append("- Guitar techniques are noted with separate parentheses:")
    output.append("  - **(b)** for a pitch bend")
    output.append("  - **(h)** for a harmonic")
    output.append("  - **(s)** for a slide between notes")
    output.append("  - **(ho)** for a hammer-on")
    output.append("  - **(po)** for a pull-off")
    output.append("- Song sections are marked with: {SECTION: name}")
    output.append("- Lyrics are included as: \"Lyric text\"\n")

    # Enhanced song metadata
    output.append(f"Title: {song_title}")
    if song_artist != 'Unknown Artist':
        output.append(f"Artist: {song_artist}")
    if song_album != 'Unknown Album':
        output.append(f"Album: {song_album}")
    if song_composer != 'Unknown Composer':
        output.append(f"Composer: {song_composer}")
    if song_copyright:
        output.append(f"Copyright: {song_copyright}")
    if song_notice:
        output.append(f"Notes: {song_notice}")
    if song_instructions:
        output.append(f"Instructions: {song_instructions}")
    if song_subtitles:
        output.append(f"Subtitles: {' / '.join(song_subtitles)}")
    output.append(f"Tempo: {tempo} BPM")
    # Present key in text (e.g., C major or A minor)
    if key_text.endswith("m"):
        output.append(f"Key: {key_text[:-1]} minor")
    else:
        output.append(f"Key: {key_text} major")
    output.append(f"Time Signature: {num}/{den}\n")

    # Helper to convert MIDI pitch number to ABC note string
    note_names = ["C","^C","D","^D","E","F","^F","G","^G","A","^A","B"]
    def midi_to_abc(pitch):
        name = note_names[pitch % 12]      # e.g., 61 % 12 = 1 -> "^C" (C#)
        octave = pitch // 12 - 1           # MIDI octave (C4=60 gives 4-1=3, but C4 is middle C in ABC)
        base_octave = 4                    # Octave number that corresponds to no comma or apostrophe (C4-B4)
        # Determine letter case and octave markers
        letter = name[1] if name.startswith('^') else name[0]  # base letter (A-G)
        if octave >= base_octave:
            # Uppercase for octave 4, lowercase for 5 and above
            abc_letter = letter.upper() if octave == base_octave else letter.lower()
            if octave > base_octave + 1:  # add apostrophes for octave > 5
                abc_letter += "'" * (octave - 5)
        else:
            # Octave below 4: uppercase with commas
            abc_letter = letter.upper()
            abc_letter += "," * (base_octave - octave)
        # Prepend accidental if needed
        return ("^" + abc_letter) if name.startswith('^') else abc_letter

    # Helper to identify chord name from a set of pitches
    def identify_chord(pitches):
        pcs = sorted({p % 12 for p in pitches})  # unique pitch classes
        if not pcs:
            return None
        # Use lowest note as tentative root
        root = pcs[0]
        rel = sorted(((pc - root) % 12) for pc in pcs)  # relative pitches from root
        # Map root to name (prefer sharps for simplicity)
        name_map = {0:"C",1:"C#",2:"D",3:"D#",4:"E",5:"F",6:"F#",7:"G",8:"G#",9:"A",10:"A#",11:"B"}
        root_name = name_map[root]
        # Recognize common chord intervals
        intervals = rel[1:]  # skip 0 which is root
        # Two-note (dyad) – only label power chords (5th)
        if len(rel) == 2:
            if rel[1] == 7:
                return f"{root_name}5"
            return None
        # Triads
        if len(rel) == 3:
            if intervals == [4,7]:
                return f"{root_name}maj"
            if intervals == [3,7]:
                return f"{root_name}min"
            if intervals == [3,6]:
                return f"{root_name}dim"
            if intervals == [4,8]:
                return f"{root_name}aug"
            if intervals == [2,7]:
                return f"{root_name}sus2"
            if intervals == [5,7]:
                return f"{root_name}sus4"
        # 4-note chords (sevenths, sixths)
        if len(rel) == 4:
            if intervals == [4,7,10]:
                return f"{root_name}7"
            if intervals == [3,7,10]:
                return f"{root_name}min7"
            if intervals == [4,7,11]:
                return f"{root_name}maj7"
            if intervals == [3,6,10]:
                return f"{root_name}min7b5"
            if intervals == [3,6,9]:
                return f"{root_name}dim7"
            if intervals == [4,7,9]:
                return f"{root_name}6"
            if intervals == [3,7,9]:
                return f"{root_name}min6"
        # For more complex chords (9ths, etc.), or unrecognized patterns, return None
        return None

    # Process each track
    tune_index = 1
    for track_idx, track in enumerate(song.tracks):
        if track.isPercussionTrack:
            continue  # skip drums/percussion

        # Identify if track is guitar or bass
        prog = track.channel.instrument  # MIDI instrument program number
        num_strings = len(track.strings)
        is_guitar = (prog is not None and 24 <= prog <= 31) or (num_strings >= 6)
        is_bass   = (prog is not None and 32 <= prog <= 39) or (4 <= num_strings <= 5)

        if not (is_guitar or is_bass):
            continue  # skip other instruments

        instrument = "Bass" if is_bass else "Guitar"
        name = track.name or f"Track {track.number}"

        # Get track-specific metadata
        track_color = getattr(track, 'color', None)
        track_description = getattr(track, 'description', '')
        track_comments = getattr(track, 'comments', '')

        # Track metadata
        output.append(f"Track: {name} ({instrument})")
        if track_description:
            output.append(f"Description: {track_description}")
        if track_comments:
            output.append(f"Comments: {track_comments}")

        # Tuning: list open string notes from low to high
        tuning_pitches = sorted([s.value for s in track.strings], reverse=True)  # highest string last
        tuning_names = [ f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][p%12]}{p//12 - 1}"
                         for p in tuning_pitches ]
        output.append("Tuning: " + " ".join(tuning_names))

        output.append("ABC Notation:")
        # ABC header for this track
        output.append(f"X:{tune_index}")
        output.append(f"T:{song_title}")
        if song_subtitles:
            for subtitle in song_subtitles:
                output.append(f"T:{subtitle}")
        output.append(f"C:{song_composer if song_composer != 'Unknown Composer' else ''}")
        output.append(f"A:{song_artist if song_artist != 'Unknown Artist' else ''}")
        output.append(f"Z:{song_album if song_album != 'Unknown Album' else ''}")
        output.append(f"N:{name} ({instrument})")
        output.append(f"M:{num}/{den}")
        output.append("L:1/16")  # Use 1/16 as base unit for better readability
        output.append(f"Q:1/4={tempo}")
        output.append(f"K:{key_text}")

        # Iterate through measures and beats
        measure_count = 0
        current_section = None

        for measure in track.measures:
            measure_count += 1

            # Check for section markers (text annotations) in measure header
            if hasattr(measure.header, 'marker') and measure.header.marker:
                marker = measure.header.marker
                section_name = marker.title if hasattr(marker, 'title') else str(marker)
                if section_name:
                    # Add a section marker to the ABC notation
                    output.append(f"{{SECTION: {section_name}}}")
                    current_section = section_name

            # Check for text annotations that might indicate sections
            for attr_name in ['text', 'direction', 'annotation', 'comment']:
                if hasattr(measure.header, attr_name) and getattr(measure.header, attr_name):
                    text = getattr(measure.header, attr_name)
                    text_value = text.value if hasattr(text, 'value') else str(text)
                    if text_value and text_value.strip():
                        section_text = text_value.strip()

                        # Check for common section names
                        section_keywords = {
                            'VERSE': ['verse', 'v1', 'v2', 'v3', 'v4', 'verse 1', 'verse 2'],
                            'CHORUS': ['chorus', 'ch', 'chor', 'refrain'],
                            'BRIDGE': ['bridge', 'br', 'middle eight'],
                            'INTRO': ['intro', 'introduction'],
                            'OUTRO': ['outro', 'ending', 'coda', 'end'],
                            'SOLO': ['solo', 'instrumental', 'inst', 'guitar solo', 'bass solo'],
                            'PRE-CHORUS': ['pre-chorus', 'pre chorus', 'prechorus', 'pre-verse'],
                            'INTERLUDE': ['interlude', 'break', 'intermezzo'],
                        }

                        section_type = None
                        for type_name, keywords in section_keywords.items():
                            if any(keyword.lower() in section_text.lower() for keyword in keywords):
                                section_type = type_name
                                break

                        if section_type:
                            output.append(f"{{SECTION: {section_type} - {section_text}}}")
                        else:
                            output.append(f"{{TEXT: {section_text}}}")

                        break  # Found text annotation, no need to check others

            # Check for measure-specific properties
            if hasattr(measure.header, 'repeatAlternative') and measure.header.repeatAlternative:
                alt = measure.header.repeatAlternative
                output.append(f"{{ALTERNATIVE: {alt}}}")

            if hasattr(measure.header, 'repeat') and measure.header.repeat:
                rep = measure.header.repeat
                if hasattr(rep, 'closings') and rep.closings:
                    output.append(f"{{REPEAT: {rep.closings} times}}")
                elif hasattr(rep, 'close') and rep.close:
                    output.append(f"{{REPEAT END}}")
                elif hasattr(rep, 'open') and rep.open:
                    output.append(f"{{REPEAT START}}")

            if not measure.voices:
                continue

            # Use the first voice (rhythm guitar tracks typically use one voice)
            voice = measure.voices[0]
            bar_content = []  # collect notations for this measure

            for beat_idx, beat in enumerate(voice.beats):
                # Check for rest (beat with no notes)
                if not beat.notes:
                    # Use 'z' for rest with the beat's duration
                    dur = beat.duration.value if beat.duration else 4
                    # IMPROVED DURATION CALCULATION FOR RESTS
                    length_multiplier = 16 / dur if dur != 0 else 16
                    if beat.duration and beat.duration.isDotted:
                        length_multiplier *= 1.5

                    if length_multiplier == 1:
                        bar_content.append("z")
                    elif length_multiplier < 1:
                        bar_content.append(f"z/{int(1/length_multiplier)}")
                    else:
                        bar_content.append(f"z{int(length_multiplier)}")
                    continue

                # Check for beat-level text annotations
                if hasattr(beat, 'text') and beat.text:
                    text = beat.text
                    text_value = text.value if hasattr(text, 'value') else str(text)
                    if text_value.strip():
                        bar_content.append(f"\"({text_value})\"")

                # If there are notes, determine if it's a chord or single note
                if len(beat.notes) > 1:
                    # Chord: get actual pitches for each note (open string pitch + fret value)
                    pitches = []
                    for note in beat.notes:
                        if note.string <= len(track.strings):
                            open_pitch = track.strings[note.string-1].value  # open string MIDI
                            pitch = open_pitch + note.value                  # add fret offset
                            pitches.append(pitch)

                    chord_label = identify_chord(pitches)

                    if chord_label:
                        # Use ABC chord symbol in brackets
                        chord_repr = f"[{chord_label}]"
                    else:
                        # Unrecognized chord – show actual notes in bracket notation
                        chord_notes = "".join(midi_to_abc(p) for p in sorted(pitches))
                        chord_repr = f"[{chord_notes}]"

                    # IMPROVED DURATION CALCULATION FOR CHORDS
                    dur = beat.duration.value if beat.duration else 4
                    length_multiplier = 16 / dur if dur != 0 else 16
                    if beat.duration and beat.duration.isDotted:
                        length_multiplier *= 1.5

                    if length_multiplier == 1:
                        final_repr = chord_repr
                    elif length_multiplier < 1:
                        final_repr = f"{chord_repr}/{int(1/length_multiplier)}"
                    else:
                        final_repr = f"{chord_repr}{int(length_multiplier)}"

                    bar_content.append(final_repr)

                else:
                    # Single note
                    note = beat.notes[0]

                    # Calculate pitch
                    open_pitch = track.strings[note.string-1].value if note.string <= len(track.strings) else 0
                    pitch = open_pitch + note.value
                    note_repr = midi_to_abc(pitch)

                    # Check for special effects on this note
                    effects = []
                    if note.effect:
                        if note.effect.bend is not None:
                            effects.append("b")
                        if getattr(note.effect, 'hammer', False):
                            hammer_type = "ho" if getattr(note.effect, 'isHammerOn', True) else "po"
                            effects.append(hammer_type)
                        if note.effect.harmonic is not None:
                            effects.append("h")
                        if getattr(note.effect, 'slides', None):
                            effects.append("s")
                        if getattr(note.effect, 'vibrato', False):
                            effects.append("v")
                        if getattr(note.effect, 'palmMute', False):
                            effects.append("pm")
                        if getattr(note.effect, 'staccato', False):
                            effects.append("st")
                        if getattr(note.effect, 'tapping', False):
                            effects.append("t")
                        if getattr(note.effect, 'tremoloPicking', False):
                            effects.append("tr")

                    if beat.effect:
                        # Slide or vibrato might also be recorded at beat level
                        if getattr(beat.effect, 'tremoloBar', None) or getattr(beat.effect, 'slide', None):
                            if "s" not in effects:  # Avoid duplicates
                                effects.append("s")
                        if getattr(beat.effect, 'vibrato', False):
                            if "v" not in effects:  # Avoid duplicates
                                effects.append("v")

                    # Append effect markers with separate parentheses for each effect
                    if effects:
                        for effect in effects:
                            note_repr += f"({effect})"

                    # IMPROVED DURATION CALCULATION FOR SINGLE NOTES
                    dur = beat.duration.value if beat.duration else 4
                    length_multiplier = 16 / dur if dur != 0 else 16
                    if beat.duration and beat.duration.isDotted:
                        length_multiplier *= 1.5

                    if length_multiplier == 1:
                        final_repr = note_repr
                    elif length_multiplier < 1:
                        final_repr = f"{note_repr}/{int(1/length_multiplier)}"
                    else:
                        final_repr = f"{note_repr}{int(length_multiplier)}"

                    bar_content.append(final_repr)

            # End of measure – join content and add a bar line

            # Add measure number for reference
            # bar_content.insert(0, f"%{measure_count}")  # Removing measure numbers

            # Break long measures into multiple lines for better readability
            if len(bar_content) > 16:  # Split long measures for readability
                chunks = [bar_content[i:i+16] for i in range(0, len(bar_content), 16)]
                for i, chunk in enumerate(chunks):
                    if i == len(chunks) - 1:  # Last chunk
                        output.append(" ".join(chunk) + " |")
                    else:
                        output.append(" ".join(chunk) + " \\")  # Line continuation
            else:
                output.append(" ".join(bar_content) + " |")

        output.append("")  # blank line between tracks
        tune_index += 1

    # Join all lines into one output string
    result = "\n".join(output)
    return result

import streamlit as st
import tempfile
import os
from openai import OpenAI
import base64
# Assuming process_guitar_pro function is defined elsewhere

# Show title and description with wider layout
st.set_page_config(
    page_title="Music Chat",
    page_icon="🎸",
    layout="wide"
)

# Custom CSS to make the chat container wider
st.markdown("""
<style>
    .stChatFloatingInputContainer {
        max-width: 1000px !important;
    }
    .stChatMessage {
        max-width: 1000px !important;
    }
    .stMarkdown {
        max-width: 1000px !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("Music Chat")
st.write("Upload a Guitar Pro file and ask questions about it. The file will be converted to ABC notation for analysis.")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "abc_notation" not in st.session_state:
    st.session_state.abc_notation = None
if "file_processed" not in st.session_state:
    st.session_state.file_processed = False
if "show_abc" not in st.session_state:
    st.session_state.show_abc = False

# Function to reset chat
def reset_chat():
    st.session_state.messages = []

# Function to toggle ABC notation visibility
def toggle_abc_view():
    st.session_state.show_abc = not st.session_state.show_abc

# Function to sanitize text for API
def sanitize_for_api(text):
    # Replace emojis and other problematic characters
    # This is a simple version - you might need more comprehensive handling
    import re
    # Replace emoji and other non-ASCII characters with their descriptions or placeholders
    sanitized = re.sub(r'[^\x00-\x7F]+', '[SYMBOL]', text)
    return sanitized

# Move API Key Input and file upload to sidebar
with st.sidebar:
    st.header("Settings")
    openai_api_key = st.text_input("OpenAI API Key", type="password")

    if openai_api_key:
        client = OpenAI(api_key=openai_api_key)

        uploaded_file = st.file_uploader(
            "Upload a Guitar Pro file",
            type=["gp3", "gp4", "gp5", "gpx", "gp"]
        )

        if st.session_state.file_processed:
            st.button("Reset Chat", on_click=reset_chat)
    else:
        st.info("Please add your OpenAI API key to continue.", icon="🔑")

# Process uploaded file
if openai_api_key and uploaded_file and not st.session_state.file_processed:
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        temp_path = tmp_file.name

    try:
        with st.spinner("Converting Guitar Pro file to ABC notation..."):
            st.session_state.abc_notation = process_guitar_pro(temp_path)
            st.session_state.file_processed = True
            st.success("File converted successfully!")

        os.unlink(temp_path)
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        if os.path.exists(temp_path):
            os.unlink(temp_path)

# Display ABC notation controls and preview AFTER file processing - outside the sidebar
if st.session_state.file_processed:
    # ABC notation controls in the main area
    st.subheader("ABC Notation")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("View/Hide ABC"):
            toggle_abc_view()

    with col2:
        # Create a button that will copy the ABC notation to clipboard
        if st.button("Copy ABC to Clipboard"):
            # Create JavaScript to copy text to clipboard
            abc_b64 = base64.b64encode(st.session_state.abc_notation.encode()).decode()
            js_code = f"""
            <script>
                const textToCopy = atob("{abc_b64}");
                const textarea = document.createElement('textarea');
                textarea.value = textToCopy;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                // Show feedback
                alert('ABC notation copied to clipboard!');
            </script>
            """

            # Use components to inject JavaScript
            st.components.v1.html(js_code, height=0)
            st.success("ABC notation copied to clipboard!")

    # Show ABC notation if view is toggled
    if st.session_state.show_abc:
        st.text_area("", st.session_state.abc_notation, height=400)

    st.markdown("---")  # Divider between ABC controls and chat

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if openai_api_key and st.session_state.file_processed:
    if prompt := st.chat_input("Ask a question about your music:"):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)

        # Display assistant response
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""

            # Include ABC notation in the system message without sanitization
            system_content = f"""You are a helpful music assistant. 

Here is the ABC notation of the piece to analyze:

{st.session_state.abc_notation}

Analyze this notation and respond to the user's query. Please do NOT reference the syntax or the ABC notation (e.g.: references to chords like [B,,,^F,,]) in your answer, instead describe them with natural language and proper music theory terminology."""

            # Prepare the messages for API call
            api_messages = [
                {
                    "role": "system",
                    "content": system_content
                }
            ]

            # Add all conversation history
            for message in st.session_state.messages:
                api_messages.append(message)

            # Generate the response
            with st.spinner("Analyzing music..."):
                try:
                    stream = client.chat.completions.create(
                        model="gpt-4o",
                        messages=api_messages,
                        stream=True,
                    )

                    # Process the streaming response
                    for chunk in stream:
                        if chunk.choices[0].delta.content:
                            full_response += chunk.choices[0].delta.content
                            # Use a simple ASCII character for the cursor instead
                            message_placeholder.markdown(full_response + "_")

                    message_placeholder.markdown(full_response)
                except Exception as e:
                    message_placeholder.error(f"Error generating response: {str(e)}")
                    full_response = "I'm sorry, there was an error analyzing your music. Please try again."

            # Add assistant response to chat history
            st.session_state.messages.append({"role": "assistant", "content": full_response})

elif openai_api_key and not st.session_state.file_processed and uploaded_file:
    st.info("Processing your file. Please wait...")
elif openai_api_key and not uploaded_file:
    st.info("Please upload a Guitar Pro file to start chatting.")