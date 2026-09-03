#version 440

// The Blackwall taking the screen.
//
// A tear opens at the centre and widens until nothing is left. What shows
// through it is not painted here: the shader draws the DESKTOP, and inside the
// tear it writes alpha zero, so the lock surface underneath is what you see
// through the hole. That is what makes it read as the wall coming through
// rather than as a picture of a wall fading in.
//
// The desktop is a still, captured the moment before the session locked. It has
// to be, because a session lock surface is the only thing the compositor
// presents once it is up — there is nothing live behind it to reveal.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    // 0 is an untouched desktop, 1 is nothing left.
    float progress;
    float aspect;
    float time;
};

layout(binding = 1) uniform sampler2D src;

float hash21(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

// How ragged the edge of the tear is at a given bearing.
//
// Every term is an integer multiple of the angle, so the whole thing is 2*pi
// periodic and the edge closes on itself. A non-integer multiple would leave a
// visible seam running out from the centre where the noise fails to meet.
float edgeNoise(float a) {
    return sin(a *  5.0 + time * 0.21) * 0.55
         + sin(a * 11.0 - time * 0.13) * 0.28
         + sin(a * 23.0 + time * 0.37) * 0.17;
}

void main() {
    vec2 uv = qt_TexCoord0;

    // Aspect-corrected, so the tear is round on screen rather than an ellipse.
    vec2 p = (uv - 0.5) * vec2(aspect, 1.0);
    float r = length(p);
    float a = atan(p.y, p.x);

    // Far enough to swallow the corners of any sane aspect ratio.
    float reach = 0.5 * sqrt(aspect * aspect + 1.0) + 0.04;

    // The tear grows on a curve rather than linearly: slow to open, then it
    // goes. A linear iris reads as a wipe; this reads as something giving way.
    float grow = progress * progress * (3.0 - 2.0 * progress);
    float edge = grow * reach * (1.0 + 0.13 * edgeNoise(a));

    // 1 well outside the tear, 0 well inside it.
    float outside = smoothstep(edge - 0.012, edge + 0.012, r);

    // --- the desktop, coming apart -----------------------------------------

    // Strongest right at the lip and falling away outward, so the picture is
    // pulled into the hole rather than shaking as a whole.
    float lip = exp(-max(0.0, r - edge) * 7.0);

    // Bands slip toward the tear. Tied to a coarse row index so it shears in
    // strips like a signal breaking up, not like a smooth warp.
    float row = floor(uv.y * 90.0);
    float slip = (hash21(vec2(row, floor(time * 12.0))) - 0.5) * 2.0;
    vec2 pull = normalize(p + 1e-6) * lip * (0.035 * slip + 0.012);

    // Colour separates as it is stretched. Sampling the three channels at
    // slightly different offsets is the whole of it.
    float split = lip * 0.012 + grow * 0.002;
    vec2 base = uv - pull;
    vec3 col;
    col.r = texture(src, base + vec2(split, 0.0)).r;
    col.g = texture(src, base).g;
    col.b = texture(src, base - vec2(split, 0.0)).b;

    // The whole picture loses its colour and its light as the wall takes it,
    // so the last of it goes dim rather than staying bright to the end.
    float drain = grow;
    float grey = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, vec3(grey * 0.85, grey * 0.30, grey * 0.34), drain * 0.85);
    col *= 1.0 - 0.55 * drain;

    // Blocks of the desktop drop out ahead of the edge, so the tear looks like
    // it is eating rather than expanding into untouched ground.
    vec2 cell = floor(vec2(uv.x * 46.0, uv.y * 26.0));
    float eaten = step(0.995 - 0.16 * lip - 0.03 * grow,
                       hash21(cell + floor(time * 9.0)));

    // --- the lip itself ----------------------------------------------------

    // A hot line where the two sides meet, and the reason the tear reads as an
    // opening rather than as a hole punched in a picture.
    float rim = exp(-abs(r - edge) * 90.0);
    float rimOuter = exp(-abs(r - edge) * 26.0);
    vec3 rimColor = vec3(1.00, 0.16, 0.20) * rim * 1.5
                  + vec3(0.55, 0.03, 0.06) * rimOuter * 0.7;

    // The rim burns through everything, including the part of the desktop that
    // has already been eaten.
    float alpha = outside * (1.0 - eaten);
    col += rimColor * max(outside, 0.35);
    alpha = max(alpha, min(1.0, rim * 1.2));

    fragColor = vec4(col, 1.0) * alpha * qt_Opacity;
}
