# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OpenGL shaders for projection mapping renderer."""

VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 in_pos;
layout(location = 1) in vec2 in_uv;

out vec2 v_uv;
out vec2 v_pos;

uniform mat4 u_mvp;
uniform vec2 u_resolution;
uniform vec2 u_canvas_size;

void main() {
    // Convert from canvas coordinates to normalized device coordinates.
    // Canvas Y grows downward (top-left origin, matching the editor) while
    // NDC Y grows upward, so Y is inverted here - without it the projection
    // comes out mirrored vertically against what the editor shows.
    vec2 normalized = in_pos / u_canvas_size;
    vec2 ndc = vec2(normalized.x * 2.0 - 1.0, 1.0 - normalized.y * 2.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_uv = in_uv;
    // Canvas-space position, needed by the projective UV path in the fragment
    // stage. Interpolating it linearly is exact here: the projection is
    // orthographic and every shape is flat.
    v_pos = in_pos;
}
"""

FRAGMENT_SHADER_TEXTURE = """
#version 330 core
in vec2 v_uv;
in vec2 v_pos;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform float u_opacity;
uniform float u_time;
uniform vec3 u_rgb_shift;  // (amount, speed, 0)
uniform mat3 u_uv_matrix;      // canvas -> UV homography (corner pin)
uniform int u_uv_projective;   // 0 = per-vertex v_uv, 1 = u_uv_matrix
uniform vec2 u_media_offset;   // shift in UV units
uniform float u_media_rotation; // radians, about the media centre
uniform int u_uv_clip;         // 1 = drop samples outside the media
uniform vec4 u_source_rect;    // (u0, v0, width, height) of the input region

// Slack on the clip test. The corner-pin divide can land a hair outside the
// unit square right on a quad's edge, and clipping that strictly would cut a
// transparent hairline along every corner-pinned surface.
const float UV_CLIP_EPS = 0.001;

void main() {
    vec2 uv = v_uv;

    // Corner pin: dividing by the homogeneous component per fragment is what
    // makes the media follow the surface in perspective. Interpolating UVs
    // per vertex instead bends the image along the triangulation diagonal.
    if (u_uv_projective == 1) {
        vec3 h = u_uv_matrix * vec3(v_pos, 1.0);
        if (abs(h.z) > 1e-9) {
            uv = h.xy / h.z;
        }
    }

    // Media transform: rotate about the media's centre, then pan. Applied
    // after the surface mapping so it repositions the content within the
    // surface rather than moving the surface itself.
    if (u_media_rotation != 0.0) {
        float c = cos(u_media_rotation);
        float s = sin(u_media_rotation);
        vec2 centred = uv - 0.5;
        uv = vec2(centred.x * c - centred.y * s, centred.x * s + centred.y * c) + 0.5;
    }
    uv -= u_media_offset;

    // Anything outside the media is genuinely empty - the bars of a `contain`
    // fit, or the gap revealed by panning. Discarding beats clamping, which
    // would smear the edge row of pixels across them.
    if (u_uv_clip == 1 &&
        (uv.x < -UV_CLIP_EPS || uv.x > 1.0 + UV_CLIP_EPS ||
         uv.y < -UV_CLIP_EPS || uv.y > 1.0 + UV_CLIP_EPS)) {
        discard;
    }

    // Input space last: everything above decides where in the *surface* this
    // fragment falls, and this maps that onto the chosen region of the media.
    // Clipping happens before the remap, so the test stays against the plain
    // unit square whatever region is selected.
    uv = u_source_rect.xy + uv * u_source_rect.zw;

    // RGB shift effect
    if (u_rgb_shift.x > 0.001) {
        float shift = u_rgb_shift.x * 0.01 * sin(u_time * u_rgb_shift.y);
        float r = texture(u_texture, uv + vec2(shift, 0.0)).r;
        float g = texture(u_texture, uv).g;
        float b = texture(u_texture, uv - vec2(shift, 0.0)).b;
        frag_color = vec4(r, g, b, u_opacity);
    } else {
        frag_color = texture(u_texture, uv) * u_opacity;
    }
}
"""

FRAGMENT_SHADER_SOLID = """
#version 330 core
out vec4 frag_color;

uniform vec4 u_color;
uniform float u_opacity;
uniform float u_time;
uniform vec3 u_rgb_shift;

void main() {
    vec4 color = u_color;

    // RGB shift effect
    if (u_rgb_shift.x > 0.001) {
        float shift = u_rgb_shift.x * sin(u_time * u_rgb_shift.y) * 0.1;
        color.r = clamp(color.r + shift, 0.0, 1.0);
        color.g = clamp(color.g - shift * 0.5, 0.0, 1.0);
        color.b = clamp(color.b + shift, 0.0, 1.0);
    }

    frag_color = vec4(color.rgb, color.a * u_opacity);
}
"""

FRAGMENT_SHADER_STROKE = """
#version 330 core
out vec4 frag_color;

uniform vec4 u_color;

void main() {
    frag_color = u_color;
}
"""

# Vertex data structure: x, y, u, v per vertex
VERTEX_FORMAT = "2f 2f"
VERTEX_STRIDE = 16  # 4 floats * 4 bytes


# --- output stage ---------------------------------------------------------
#
# The canvas is composited once into a texture; each projector then draws that
# texture through its own keystone, colour and edge blend. Doing it in a second
# pass rather than per shape is what makes soft-edge correct: the ramp has to
# attenuate the *finished* image, or overlapping surfaces get darkened twice.

VERTEX_SHADER_OUTPUT = """
#version 330 core
layout(location = 0) in vec2 in_pos;   // output frame, 0..1
layout(location = 1) in vec2 in_uv;    // unused; kept for the shared VBO layout

out vec2 v_frame;

void main() {
    // Y flips for the same reason as the canvas pass: the frame is described
    // top-left origin, NDC grows upward.
    gl_Position = vec4(in_pos.x * 2.0 - 1.0, 1.0 - in_pos.y * 2.0, 0.0, 1.0);
    v_frame = in_pos;
}
"""

FRAGMENT_SHADER_OUTPUT = """
#version 330 core
in vec2 v_frame;
out vec4 frag_color;

uniform sampler2D u_canvas;
uniform vec4 u_region;        // (u0, v0, width, height) of the canvas shown
uniform mat3 u_keystone;      // output frame -> unwarped frame
uniform int u_has_keystone;

uniform vec4 u_blend;         // ramp widths: left, right, top, bottom
uniform float u_blend_gamma;

uniform float u_brightness;
uniform float u_contrast;
uniform float u_gamma;
uniform vec3 u_gain;

// One edge's contribution to the blend ramp. Outside the ramp this is 1.
//
// The S-curve matters: two projectors facing each other across an overlap
// see complementary positions t and 1-t, and this pair sums to exactly 1 for
// *any* exponent. A plain pow(t, k) does not - at the middle of the overlap
// two half-lit projectors would add up to more than one projector's worth and
// leave a bright band down the seam, which is precisely the artefact edge
// blending exists to remove. The exponent stays tunable because projectors
// are not linear, so the value that looks seamless is found by eye.
float edge_ramp(float distance_in, float width, float exponent) {
    if (width <= 0.0) {
        return 1.0;
    }
    float t = clamp(distance_in / width, 0.0, 1.0);
    if (t < 0.5) {
        return 0.5 * pow(2.0 * t, exponent);
    }
    return 1.0 - 0.5 * pow(2.0 * (1.0 - t), exponent);
}

void main() {
    vec2 frame = v_frame;

    // Keystone: squaring the projector against the surface. Same projective
    // divide as the per-surface corner pin, for the same reason - a linear
    // interpolation here would bend the image across the diagonal.
    if (u_has_keystone == 1) {
        vec3 h = u_keystone * vec3(frame, 1.0);
        if (abs(h.z) > 1e-9) {
            frame = h.xy / h.z;
        }
        if (frame.x < 0.0 || frame.x > 1.0 || frame.y < 0.0 || frame.y > 1.0) {
            // Outside the warped quad is off the surface entirely.
            frag_color = vec4(0.0, 0.0, 0.0, 1.0);
            return;
        }
    }

    // The canvas pass inverts Y on its way into the framebuffer, so canvas
    // row 0 lands at texture v = 1. Sampling straight through would hand the
    // projector a vertically mirrored image - invisible on a symmetric test
    // pattern, obvious the moment there is text on screen.
    vec2 canvas_uv = u_region.xy + frame * u_region.zw;
    vec3 rgb = texture(u_canvas, vec2(canvas_uv.x, 1.0 - canvas_uv.y)).rgb;

    // Colour, before the blend: the ramp is a physical light attenuation and
    // has to be the last thing applied.
    rgb = (rgb - 0.5) * u_contrast + 0.5 + u_brightness;
    rgb = clamp(rgb, 0.0, 1.0) * u_gain;
    rgb = pow(clamp(rgb, 0.0, 1.0), vec3(1.0 / u_gamma));

    float ramp = edge_ramp(frame.x, u_blend.x, u_blend_gamma)
               * edge_ramp(1.0 - frame.x, u_blend.y, u_blend_gamma)
               * edge_ramp(frame.y, u_blend.z, u_blend_gamma)
               * edge_ramp(1.0 - frame.y, u_blend.w, u_blend_gamma);
    rgb *= ramp;

    frag_color = vec4(rgb, 1.0);
}
"""
