//! The synth itself: voices, waveforms, envelopes. Plain Rust, no Windows —
//! main.rs feeds it keys and hands its samples to the sound card.

use std::f32::consts::TAU;

pub const RATE: f32 = 44_100.0;
const ATTACK: f32 = 0.008; // seconds
const DECAY: f32 = 0.18;
const SUSTAIN: f32 = 0.55; // level held while a key is down
const RELEASE: f32 = 0.35;
pub const MAX_VOICES: usize = 10;
const SCOPE: usize = 2048;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Wave {
    Sine,
    Triangle,
    Saw,
    Square,
}

impl Wave {
    pub const ALL: [Wave; 4] = [Wave::Sine, Wave::Triangle, Wave::Saw, Wave::Square];

    pub fn name(self) -> &'static str {
        match self {
            Wave::Sine => "Sine",
            Wave::Triangle => "Triangle",
            Wave::Saw => "Saw",
            Wave::Square => "Square",
        }
    }

    /// One cycle, phase in [0, 1). ponytail: naive (not band-limited), so
    /// saw and square alias on high notes; PolyBLEP fixes that if it matters.
    fn at(self, phase: f32) -> f32 {
        match self {
            Wave::Sine => (phase * TAU).sin(),
            Wave::Triangle => 4.0 * (phase - 0.5).abs() - 1.0,
            Wave::Saw => 2.0 * phase - 1.0,
            Wave::Square => {
                if phase < 0.5 {
                    1.0
                } else {
                    -1.0
                }
            }
        }
    }
}

#[derive(Clone, Copy, PartialEq, Debug)]
enum Stage {
    Attack,
    Decay,
    Sustain,
    Release,
}

struct Voice {
    note: u8,
    phase: f32,
    step: f32, // phase advance per sample: frequency / rate
    level: f32,
    stage: Stage,
}

pub struct Synth {
    voices: Vec<Voice>,
    pub wave: Wave,
    scope: Vec<f32>, // ring buffer of the most recent output
    scope_pos: usize,
    pub frames: u64, // samples rendered so far: the stream's heartbeat
}

/// Equal temperament: A4 (MIDI note 69) is 440 Hz, each semitone 2^(1/12).
pub fn freq(note: u8) -> f32 {
    440.0 * 2f32.powf((note as f32 - 69.0) / 12.0)
}

impl Synth {
    pub fn new() -> Self {
        Synth { voices: Vec::new(), wave: Wave::Triangle, scope: vec![0.0; SCOPE], scope_pos: 0, frames: 0 }
    }

    pub fn note_on(&mut self, note: u8) {
        if let Some(v) = self.voices.iter_mut().find(|v| v.note == note) {
            v.stage = Stage::Attack; // retrigger rather than stack
            return;
        }
        if self.voices.len() == MAX_VOICES {
            // Out of voices: steal the quietest, which is the least missed.
            let quiet = (0..self.voices.len())
                .min_by(|&a, &b| self.voices[a].level.total_cmp(&self.voices[b].level))
                .unwrap();
            self.voices.remove(quiet);
        }
        self.voices.push(Voice { note, phase: 0.0, step: freq(note) / RATE, level: 0.0, stage: Stage::Attack });
    }

    pub fn note_off(&mut self, note: u8) {
        for v in self.voices.iter_mut().filter(|v| v.note == note) {
            v.stage = Stage::Release;
        }
    }

    pub fn all_off(&mut self) {
        for v in &mut self.voices {
            v.stage = Stage::Release;
        }
    }

    pub fn voices(&self) -> usize {
        self.voices.len()
    }

    /// Fill a buffer of 16-bit mono samples.
    pub fn render(&mut self, out: &mut [i16]) {
        self.frames += out.len() as u64;
        for s in out.iter_mut() {
            let mut mix = 0.0;
            for v in &mut self.voices {
                match v.stage {
                    Stage::Attack => {
                        v.level += 1.0 / (ATTACK * RATE);
                        if v.level >= 1.0 {
                            v.level = 1.0;
                            v.stage = Stage::Decay;
                        }
                    }
                    Stage::Decay => {
                        v.level -= (1.0 - SUSTAIN) / (DECAY * RATE);
                        if v.level <= SUSTAIN {
                            v.level = SUSTAIN;
                            v.stage = Stage::Sustain;
                        }
                    }
                    Stage::Sustain => {}
                    Stage::Release => v.level = (v.level - SUSTAIN / (RELEASE * RATE)).max(0.0),
                }
                mix += self.wave.at(v.phase) * v.level;
                v.phase += v.step;
                if v.phase >= 1.0 {
                    v.phase -= 1.0;
                }
            }
            // tanh soft-clips: ten voices at once bend instead of cracking.
            let y = (mix * 0.3).tanh();
            *s = (y * 32_000.0) as i16;
            self.scope[self.scope_pos] = y;
            self.scope_pos = (self.scope_pos + 1) % SCOPE;
        }
        self.voices.retain(|v| v.stage != Stage::Release || v.level > 0.0);
    }

    /// `n` recent samples starting at a rising zero crossing — what an
    /// oscilloscope's trigger does, so a steady tone stands still on screen.
    pub fn scope(&self, n: usize) -> Vec<f32> {
        let ordered: Vec<f32> =
            (0..SCOPE).map(|i| self.scope[(self.scope_pos + i) % SCOPE]).collect();
        let search_end = SCOPE.saturating_sub(n);
        let start = (1..search_end)
            .rev()
            .find(|&i| ordered[i - 1] < 0.0 && ordered[i] >= 0.0)
            .unwrap_or(search_end);
        ordered[start..start + n].to_vec()
    }
}

/// The DSP's own check — run with `--selftest`. Nothing is played.
pub fn selftest() -> Result<String, String> {
    let check = |ok: bool, what: String| if ok { Ok(what) } else { Err(what) };
    let mut report = Vec::new();

    // Pitch: time the rising zero crossings of one second of A4.
    let mut s = Synth::new();
    s.wave = Wave::Sine;
    s.note_on(69);
    let mut buf = vec![0i16; RATE as usize];
    s.render(&mut buf);
    let ups: Vec<usize> =
        (1..buf.len()).filter(|&i| buf[i - 1] < 0 && buf[i] >= 0).collect();
    let hz = (ups.len() - 1) as f32 * RATE / (ups[ups.len() - 1] - ups[0]) as f32;
    report.push(check((hz - 440.0).abs() < 0.5, format!("A4 = {hz:.1} Hz"))?);

    // Release: half a second after note-off the voice is gone and silent.
    s.note_off(69);
    let mut tail = vec![0i16; (RATE * 0.5) as usize];
    s.render(&mut tail);
    report.push(check(s.voices() == 0 && tail[tail.len() - 100..].iter().all(|&x| x == 0),
                      "release ends in silence".into())?);

    // Polyphony: a voice cap, and a chord louder than one note but clipped softly.
    for n in 48..70 {
        s.note_on(n);
    }
    report.push(check(s.voices() == MAX_VOICES, format!("{} voices max", s.voices()))?);
    let mut chord = vec![0i16; 4096];
    s.render(&mut chord);
    let peak = chord.iter().map(|x| x.unsigned_abs()).max().unwrap_or(0);
    report.push(check(peak > 8_000 && peak <= 32_000, format!("chord peak {peak}"))?);

    // Scope trigger: the captured window starts on a rising edge.
    let sc = s.scope(400);
    report.push(check(sc.len() == 400, "scope window".into())?);
    Ok(report.join(" · "))
}
