"""Synthetic acceleration windows; never apply spectra to the scalar RMS channel."""

import math
from typing import Any

import numpy as np
from scipy.signal import fftconvolve, hilbert
from scipy.stats import kurtosis

from app.datapulse.configuration import VibrationProfile


def synthesize_window(
    profile: VibrationProfile,
    rng: np.random.Generator,
    severity: float = 0,
) -> dict[str, Any]:
    count = int(profile.sample_rate_hz * profile.duration_seconds)
    time = np.arange(count) / profile.sample_rate_hz
    geometry = profile.bearing_geometry
    ratio = (
        geometry.ball_diameter_mm
        / geometry.pitch_diameter_mm
        * math.cos(math.radians(geometry.contact_angle_degrees))
    )
    bpfo = geometry.rolling_elements * profile.shaft_frequency_hz / 2 * (1 - ratio)
    bpfi = geometry.rolling_elements * profile.shaft_frequency_hz / 2 * (1 + ratio)
    frequency = bpfo if profile.defect == "outer" else bpfi
    acceleration = rng.normal(0, profile.broadband_sigma, count)
    for harmonic, amplitude in enumerate(profile.harmonic_amplitudes, start=1):
        acceleration += amplitude * np.sin(2 * np.pi * harmonic * profile.shaft_frequency_hz * time)
    impulses = np.zeros(count)
    indices = (
        np.arange(0, profile.duration_seconds, 1 / frequency) * profile.sample_rate_hz
    ).astype(int)
    indices = indices[indices < count]
    impulses[indices] = (
        profile.impulse_amplitude
        * severity
        * (
            1
            + profile.modulation_fraction
            * np.cos(2 * np.pi * profile.shaft_frequency_hz * time[indices])
        )
    )
    response_time = np.arange(
        min(count, int(profile.decay_seconds * 10 * profile.sample_rate_hz)), dtype=float
    )
    response_time = response_time / profile.sample_rate_hz
    response = np.exp(-response_time / profile.decay_seconds) * np.sin(
        2 * np.pi * profile.resonance_hz * response_time
    )
    acceleration += fftconvolve(impulses, response)[:count]
    rms = float(np.sqrt(np.mean(acceleration**2)))
    envelope = np.abs(hilbert(acceleration))
    spectrum = 2 * np.abs(np.fft.rfft(envelope - np.mean(envelope))) / count
    return {
        "sample_rate_hz": profile.sample_rate_hz,
        "unit": "m/s^2",
        "samples": acceleration.tolist(),
        "rms": rms,
        "kurtosis": float(kurtosis(acceleration, fisher=False)),
        "crest_factor": float(np.max(np.abs(acceleration)) / max(rms, 1e-12)),
        "bpfo_hz": bpfo,
        "bpfi_hz": bpfi,
        "envelope_frequencies_hz": np.fft.rfftfreq(count, 1 / profile.sample_rate_hz).tolist(),
        "envelope_amplitudes": spectrum.tolist(),
    }
