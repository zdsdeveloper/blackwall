#version 440

// Blackwall glitch field. Sits behind the logo on the lock surface: a dark
// carrier with digital static, torn scan bands, and occasional red/white
// block artifacts.
//
// Every random source is keyed off a *quantised* clock rather than the raw
// one, so the noise steps like a refreshing signal instead of drifting
// smoothly — smooth noise reads as fog, stepped noise reads as broken data.
//
// Uniforms are all scalar floats on purpose: std140 packs them consecutively
// with no alignment traps to get wrong.
//
// Build: qsb --qt6 -o glitch.frag.qsb glitch.frag

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float intensity;
    float aspect;
    float scanScale;
    // Appended, all scalar floats, all defaulting to the lock surface's
    // original behaviour so that surface is unchanged by their existence.
    // The station wants the same field much finer and much slower: sand
    // rather than snow, drifting rather than snapping.
    float grainScale;
    float stepRate;
    float artifacts;
};

float hash21(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    vec2 uv = qt_TexCoord0;

    // Two clocks: `frame` drives the static and blocks, `slow` holds a tear
    // in place long enough to register before it moves.
    float frame = floor(time * stepRate);
    float slow  = floor(time * stepRate / 6.0);

    // --- horizontal tear -----------------------------------------------
    // A couple of bands per slice slip sideways, the way a bad feed does.
    float bandRow    = floor(uv.y * 28.0);
    float bandSeed   = hash21(vec2(bandRow, slow));
    float tearing    = step(0.93, bandSeed) * artifacts;
    float tearAmount = (hash21(vec2(bandRow, slow + 7.0)) - 0.5) * 0.08 * tearing;
    vec2  tuv        = vec2(uv.x + tearAmount, uv.y);

    // --- fine static ------------------------------------------------------
    float grain       = hash21(floor(vec2(tuv.x * 620.0 * grainScale * aspect,
                                          tuv.y * 350.0 * grainScale)) + frame);
    float staticField = smoothstep(0.72, 1.0, grain);

    // --- block artifacts --------------------------------------------------
    vec2  cellId   = floor(vec2(tuv.x * 18.0, tuv.y * 34.0));
    float block    = step(0.982, hash21(cellId + frame * 0.37)) * artifacts;
    float blockHot = step(0.9965, hash21(cellId + frame * 0.91)) * artifacts;

    // --- scanlines --------------------------------------------------------
    // Tied to pixel height so the line pitch stays ~2px on any output rather
    // than moireing at a fixed uv frequency.
    float scan     = 0.5 + 0.5 * sin(uv.y * scanScale * 3.14159);
    float scanDark = 1.0 - 0.35 * scan;

    // --- vignette ---------------------------------------------------------
    vec2  centered = (uv - 0.5) * vec2(aspect, 1.0);
    float vig      = 1.0 - smoothstep(0.35, 0.95, length(centered));

    // --- compose ----------------------------------------------------------
    vec3 col = vec3(0.010, 0.004, 0.006);
    col += vec3(0.055, 0.010, 0.014) * staticField;
    col += vec3(0.420, 0.045, 0.060) * block;
    col += vec3(0.750, 0.720, 0.780) * blockHot;
    col += vec3(0.100, 0.012, 0.018) * tearing * 0.6;

    col *= scanDark;
    col *= mix(0.35, 1.0, vig);
    col *= intensity;

    fragColor = vec4(col, 1.0) * qt_Opacity;
}
