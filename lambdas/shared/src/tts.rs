//! Text-to-Speech utilities using Amazon Polly.

use aws_sdk_polly::types::{Engine, OutputFormat, VoiceId};
use aws_sdk_polly::Client as PollyClient;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum TtsError {
    #[error("Polly synthesis failed: {0}")]
    SynthesisFailed(String),
    #[error("Invalid audio data")]
    InvalidAudio,
}

/// Text-to-Speech service using Amazon Polly.
pub struct TtsService {
    client: PollyClient,
    voice_id: VoiceId,
    engine: Engine,
}

impl TtsService {
    /// Create a new TTS service with default settings.
    pub fn new(client: PollyClient) -> Self {
        Self {
            client,
            voice_id: VoiceId::Matthew, // Neural voice
            engine: Engine::Neural,
        }
    }

    /// Create with a specific voice.
    pub fn with_voice(client: PollyClient, voice_id: VoiceId) -> Self {
        Self {
            client,
            voice_id,
            engine: Engine::Neural,
        }
    }

    /// Synthesize text to speech, returning MP3 audio bytes.
    pub async fn synthesize(&self, text: &str) -> Result<Vec<u8>, TtsError> {
        // Limit text length for Polly (max ~3000 characters per request)
        let text = if text.len() > 2900 {
            format!("{}... Message truncated.", &text[..2900])
        } else {
            text.to_string()
        };

        let response = self
            .client
            .synthesize_speech()
            .text(&text)
            .voice_id(self.voice_id.clone())
            .engine(self.engine.clone())
            .output_format(OutputFormat::Mp3)
            .send()
            .await
            .map_err(|e| TtsError::SynthesisFailed(e.to_string()))?;

        let audio_stream = response
            .audio_stream
            .collect()
            .await
            .map_err(|e| TtsError::SynthesisFailed(e.to_string()))?;

        Ok(audio_stream.to_vec())
    }

    /// Synthesize with SSML markup for better control.
    pub async fn synthesize_ssml(&self, ssml: &str) -> Result<Vec<u8>, TtsError> {
        let response = self
            .client
            .synthesize_speech()
            .text(ssml)
            .text_type(aws_sdk_polly::types::TextType::Ssml)
            .voice_id(self.voice_id.clone())
            .engine(self.engine.clone())
            .output_format(OutputFormat::Mp3)
            .send()
            .await
            .map_err(|e| TtsError::SynthesisFailed(e.to_string()))?;

        let audio_stream = response
            .audio_stream
            .collect()
            .await
            .map_err(|e| TtsError::SynthesisFailed(e.to_string()))?;

        Ok(audio_stream.to_vec())
    }
}

/// Available neural voices for TTS.
pub mod voices {
    use aws_sdk_polly::types::VoiceId;

    /// US English male voice (conversational).
    pub const MATTHEW: VoiceId = VoiceId::Matthew;
    /// US English female voice (conversational).
    pub const JOANNA: VoiceId = VoiceId::Joanna;
    /// US English female voice (newscaster style).
    pub const AMY: VoiceId = VoiceId::Amy;
    /// British English male voice.
    pub const BRIAN: VoiceId = VoiceId::Brian;
}
