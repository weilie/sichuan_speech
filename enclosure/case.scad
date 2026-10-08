// Sichuan Speech enclosure
//
// Two-piece column: base + lid, snap-fit.
//   base   — houses Pi 3B v1.2 + ReSpeaker 2-Mics HAT V2 stack,
//            cable grommet hole on the back wall
//   lid    — cups over the base; top face holds the Dayton DMA45-4
//            speaker (top-firing). Its two 3 mm mic holes (v1–v15)
//            went in v16; the base's grille band is the mic path.
//   v15    — big mic ports cut into the BASE side walls, to test
//            whether a short direct air path recovers the 7.8 dB the
//            closed lid costs. Test print: openings are deliberately
//            oversized.
//   v16    — refinement pass after the v15c print: rounded vertical
//            corners and chamfered edges on both parts, the six test
//            windows replaced by one slotted grille band on the -X
//            wall (back it with speaker cloth), and the lid's two
//            misplaced Ø3 mm mic holes removed.
//
// Iteration policy: place mic hole positions from best guess for v1
// print, then refine after test-fit.

// ----- Board & driver dimensions -----
// Pi orientation in the case (long axis VERTICAL):
//   -X wall  = GPIO edge (long, "left" — nothing external)
//   +X wall  = port edge (long, "right" — micro-USB, HDMI, audio)
//   -Y wall  = SD-card edge (short, "bottom")
//   +Y wall  = USB-stack edge (short, "top" — USB + Ethernet)
// The Pi sits tight in the -X, -Y, +Y corner. The port edge (+X) is
// open toward a large chamber for the micro-USB plug + cable.
pi_l          = 56;    // Pi short axis, along case X
pi_w          = 85;    // Pi long axis, along case Y
pi_h_stack    = 44;    // Pi board top-of-tallest-component to floor
                       // + GPIO connector + HAT board thickness.
                       // Give a bit of slack above HAT before lid.
                       // Raised +10 mm in v7 for more interior room.
pi_mount_dx   = 49;    // Mounting-hole spacing along case X (short axis)
pi_mount_dy   = 58;    // Mounting-hole spacing along case Y (long axis)
pi_mount_edge = 3.5;   // Distance from Pi board corners to hole centres
pi_screw_hole = 2.4;   // M2.5 self-tapping into plastic post

// Dayton DMA45-4 (values from the official spec sheet:
// daytonaudio.com/images/resources/295-580--dayton-audio-dma45-4-
// specification-sheet.pdf).
sp_flange     = 46;    // Square flange side length
sp_flange_t   = 3;     // Flange thickness
sp_depth      = 26.1;  // Total driver depth (flange top → magnet)
sp_screw_pat  = 36;    // Screw pattern spacing (corner-to-corner)
sp_baffle_cut = 40;    // Recommended baffle cutout diameter — the
                       // round driver frame protrudes through this
                       // hole when front-mounted
sp_screw_dia  = 3;     // v13: uniform Ø3 mm through lid top AND boss
                       // pilot. M3 self-taps the full 8 mm depth,
                       // held by plastic threads at both faces.
                       // A printed Ø3 mm hole already grips M3
                       // snugly.

// Speaker is FRONT-mounted (v11): driver drops in from above,
// flange rests on top of the lid, foam gasket compresses against
// the lid's outer surface for an air-tight seal. 4 × M3 screws
// come from above, through the flange holes, through clearance
// holes in the lid, and thread into short bosses on the lid's
// underside.
sp_boss_dia   = 7;     // Boss outer diameter on the lid interior
sp_boss_h     = 5;     // Boss length hanging down from the top face
sp_boss_pilot = 3;     // v13: matches sp_screw_dia so the whole
                       // hole through lid+boss is a single Ø3 mm
                       // bore (no step change). See sp_screw_dia.

// ---- (v15) Mic ports in the BASE side walls ----
// Measured 2026-09-19: closing the lid costs 4.9 dB of signal and
// raises the noise floor 2.9 dB — a net 7.8 dB SNR penalty. Wake word
// fires 4/4 with the lid off and 1/4 with it on. The cause is that
// both HAT mics face UP into a deep sealed cavity that also contains
// the speaker, and their only path to outside air is a 3 mm hole in
// the lid's top face, tens of mm away and placed by guess.
//
// This version is a TEST PRINT, not the final answer. It asks one
// question: does giving the mics a direct, short path to outside air
// recover the lost 7.8 dB? So the openings are deliberately far larger
// than a finished design would use — if holes this generous do not
// help, holes are not the fix and the board must be relocated to sit
// under the enclosure's outer surface (see docs/next-session.md §0).
//
// Set either flag false to isolate which opening did the work.
mic_port_y_walls = false;  // big ports in the -Y and +Y walls (v15
                           // test only; off since v16)
mic_port_x_wall  = true;   // grille band in the -X (GPIO) wall

// Mic X position, re-measured from build photos 2026-09-19 and NOT the
// same as the lid's long-standing guess. Scaling against the HAT's
// micro-USB receptacle (7.4 mm shell) puts each mic ~7.4 mm inward
// from the HAT's GPIO-header edge, right beside a corner mounting
// hole — not the ~28 mm the lid's mic holes (v1–v15) assumed.
// That is a 20 mm error, and it matters: it means the -X (GPIO) wall
// is ~10 mm from the mics while the -Y/+Y walls are ~20-24 mm away
// AND 21 mm off in X. The -X wall is the right wall to open.
mic_x_from_gpio_edge = 7.4;

// 18, not 36: once mic_x moved from the guessed 33.5 to the measured
// 12.9, a 36 mm port centred on it ran from x = -5.1, i.e. off the end
// of the wall, which prints as an open notch in the corner instead of
// a port. These are the SECONDARY openings now anyway — the -X wall is
// where the mics actually are.
mic_port_w    = 18;    // Along the wall (case X) — wall is 99 long
mic_port_h    = 18;    // Vertical extent
mic_port_r    = 3;     // Corner radius: printable, and no stress riser
                       // at a sharp corner in a 3 mm wall

// (v16) Grille band in the -X wall, replacing v15's four 16 × 18 mm
// windows. Mic Y positions measured from the 2026-10-05 build photos,
// scaled against the HAT's 58 mm mounting-hole pitch: each mic sits
// ~2 mm in from a short end of the HAT, i.e. world y ≈ 10.5 and 71.5.
// v15's windows had the second one dead behind a rib. A band of narrow
// slots along the whole wall covers both without depending on that
// measurement, keeps fingers and debris out, and still vents the Pi.
// It is NOT a dust seal on its own: glue a strip of acoustically
// transparent speaker cloth across the inside face.
// Slot 0 is centred on the first mic and the pitch is derived from the
// mic spacing (the nearest whole number of ~4 mm pitches between them,
// 15, so 61 / 15 = 4.067 mm), which puts a slot centre on BOTH measured
// positions. A fixed 4 mm pitch could not: it left one mic at a slot
// edge and, once the band's start moved, the other dead behind a rib.
// The band runs to within base_r + 0.5 of the far corner (the corner
// arc ends at y = base_r).
mic_y_a        = 10.5; // Measured mic positions, world y (2026-10-05)
mic_y_b        = 71.5;
mic_slot_w     = 2;    // Slot width along the wall
mic_slot_pitch = (mic_y_b - mic_y_a) / round((mic_y_b - mic_y_a) / 4);
mic_slot_h     = 14;   // Vertical extent, starting just under the mic
                       // plane: the mics face up, so opening below
                       // the HAT only exposes its edge

// ----- (v16) Edge treatment -----
// The base prints floor-down, so its bottom edge starts on the bed,
// where a 45° chamfer prints clean and a fillet does not. The lid's
// top edge takes a fillet, which is why the lid now prints top-face-up
// (see lid_top_r).
base_r        = 8;     // Base outer vertical-corner radius. Interior
                       // radius is base_r - wall_t = 5, which the Pi's
                       // own 3 mm corners clear by ~2 mm.
base_edge_c   = 1.5;   // Chamfer on the base's bottom edge
lid_top_r     = 6;     // Fillet on the lid's top edge. A true round,
                       // so the lid is printed TOP-FACE-UP with
                       // supports inside the cup: printed top-down
                       // the round sits on the bed and comes out
                       // rough even on supports. Leaves 2.8 mm of
                       // plastic at the chamber's inside corner.
lid_rim_c     = 0.6;   // Chamfer on the lid's lower rim

// hat_top_z / mic_port_z are DERIVED and live further down with the
// other derived values, because they depend on floor_t, which is
// defined after this block. OpenSCAD does not resolve that forward
// reference: it warns "Ignoring unknown variable", the value becomes
// undef, and every port silently cuts NOTHING while still rendering a
// clean manifold base. Caught only because the genus did not change.

cable_dia     = 12;    // Grommet must clear the CanaKit micro-USB
                       // plug + strain-relief boot (~11 mm wide),
                       // NOT just the bare cable. Started at 9 mm
                       // (v1–v11) but plug wouldn't pass through.

// ----- Enclosure dimensions -----
wall_t        = 3;     // Side-wall thickness
floor_t       = 3;     // Base floor thickness
lid_top_t     = 3;     // Lid top-face thickness
// Clearances — v10 adds a uniform +2 mm on every side so the Pi
// doesn't scrape any wall during install.
gpio_x_clear  = 2.5;   // -X wall (LEFT, GPIO edge)
port_x_clear  = 34.5;  // +X wall (RIGHT, port edge) — big chamber
                       // for micro-USB plug + cable
sd_y_clear    = 5.5;   // -Y wall (BOTTOM, SD-card edge, includes
                       // ~3 mm for the SD card sticking out)
usb_y_clear   = 2.5;   // +Y wall (TOP, USB-stack edge)

// With these values the interior comes out truly square:
//   inner_l = 56 + 2.5 + 34.5 = 93 mm
//   inner_w = 85 + 5.5 + 2.5  = 93 mm
//   outer   = 99 × 99 mm

// Pi micro-USB port location: on the +X port edge, 10 mm from the
// -Y (SD-card) end. Y-coordinate along the port edge, in Pi-local
// (rotated) coordinates.
pi_micro_usb_y_in_pi = 10;

// Pi 3B LEDs (PWR + ACT) on the top surface, near the -Y (SD-card)
// and +X (port) corner. Pi-local coords in the rotated frame. Recorded
// for the -Y wall LED slit in base(); the lid's viewing hole that
// used them went in v14.
pi_led_x_in_pi = 53;   // Near +X port edge (= pi_l - 3)
pi_led_y_in_pi = 11.5; // Near -Y SD-card edge

// ----- Snap-fit -----
snap_bump_h   = 1.0;   // How far snap bump protrudes from base wall
snap_bump_l   = 12;    // Length of the bump along the wall
snap_bump_z_from_top_of_base = 5;

// ----- Lid fit -----
// The lid slides over the outside of the base's top rim.
// Its outer footprint is therefore bigger than the base's outer
// footprint by 2 * lid_wall on each axis.
lid_wall            = 2;   // Lid wall thickness in the lip section
lid_lip             = 12;  // Depth the lid overlaps the base outer
lid_lip_clearance   = 0.3; // Gap between base outer wall and lid inner
                           // wall in the lip section

// ----- Derived -----
inner_l = pi_l + gpio_x_clear + port_x_clear;
inner_w = pi_w + sd_y_clear + usb_y_clear;
base_h  = floor_t + pi_h_stack;

// (v15) Height of the HAT's top surface above the base's outer ground,
// and therefore of the mic ports. Derived rather than guessed so it
// stays correct if the standoffs change:
//   floor_t   top of floor
//   + 4       standoff (pi_standoff default h)
//   + 1.4     Pi PCB
//   + 8.5     GPIO header
//   + 1.6     HAT PCB
hat_top_z  = floor_t + 4 + 1.4 + 8.5 + 1.6;     // ≈ 18.5
mic_port_z = hat_top_z - mic_port_h / 2 + 2;    // band straddling the
                                                // mic plane, biased up
mic_slot_z = hat_top_z - 2;                     // (v16) grille band
outer_l = inner_l + 2 * wall_t;
outer_w = inner_w + 2 * wall_t;

// Pi origin (Pi's -X, -Y corner) in interior coords (relative to
// inside face of the -X and -Y walls). Pi is tight in that corner.
pi_x0 = gpio_x_clear;
pi_y0 = sd_y_clear;

lid_outer_l = outer_l + 2 * lid_wall;
lid_outer_w = outer_w + 2 * lid_wall;
lid_h       = lid_top_t + sp_depth + 4; // top face + speaker + slack

$fn = 60;

// ===== Modules =====

module pi_standoff(h = 4) {
    difference() {
        cylinder(h = h, d = 6);
        translate([0, 0, -0.1])
            cylinder(h = h + 0.2, d = pi_screw_hole);
    }
}

module pi_standoffs_group() {
    // Pi board sits corner-aligned at (pi_x0, pi_y0) relative to
    // the inner cavity. Its mounting holes are pi_mount_edge from
    // each corner of the board.
    x0 = pi_x0 + pi_mount_edge;
    y0 = pi_y0 + pi_mount_edge;
    for (x = [x0, x0 + pi_mount_dx],
         y = [y0, y0 + pi_mount_dy])
        translate([x, y, 0]) pi_standoff();
}

module rrect(l, w, r) {
    // 2D rounded rectangle, corner at the origin.
    translate([r, r])
        offset(r = r)
            square([l - 2 * r, w - 2 * r]);
}

module rbox(l, w, h, r, c_bot = 0, c_top = 0, r_top = 0) {
    // Box with rounded vertical corners and optional 45° chamfers on
    // the bottom / top edges, or a fillet of radius r_top on the top
    // edge instead. Corner at the origin.
    top = max(c_top, r_top);
    hull() {
        if (c_bot > 0)
            translate([c_bot, c_bot, 0])
                linear_extrude(0.01)
                    rrect(l - 2 * c_bot, w - 2 * c_bot, r - c_bot);
        translate([0, 0, c_bot])
            linear_extrude(h - c_bot - top)
                rrect(l, w, r);
        if (r_top > 0)
            for (a = [0 : 5 : 85]) {
                i = r_top * (1 - cos(a));    // inset at this height
                translate([i, i, h - r_top + r_top * sin(a)])
                    linear_extrude(0.01)
                        rrect(l - 2 * i, w - 2 * i, r - i);
            }
        if (c_top > 0)
            translate([c_top, c_top, h - 0.01])
                linear_extrude(0.01)
                    rrect(l - 2 * c_top, w - 2 * c_top, r - c_top);
    }
}

module rounded_slot_y(w, h, r, depth) {
    // Rounded rectangle extruded along +Y: cuts through a -Y / +Y wall.
    // w runs along X, h along Z, measured from the translate origin.
    hull()
        for (dx = [r, w - r], dz = [r, h - r])
            translate([dx, 0, dz])
                rotate([-90, 0, 0])
                    cylinder(h = depth, r = r);
}

module rounded_slot_x(w, h, r, depth) {
    // Same, extruded along +X: cuts through the -X wall. w runs along
    // Y, h along Z. Kept as its own module rather than rotating the
    // Y version, because rotating it sends the depth the wrong way and
    // the cut lands outside the wall, removing nothing.
    hull()
        for (dy = [r, w - r], dz = [r, h - r])
            translate([0, dy, dz])
                rotate([0, 90, 0])
                    cylinder(h = depth, r = r);
}

module base_mic_ports() {
    // Mic X position, from the measured mic_x_from_gpio_edge (the lid's
    // old ~28 mm guess was 20 mm off; see that constant). Only the
    // Y-wall ports need it: the -X grille band runs the length of the
    // wall, so it depends on no mic position at all.
    mic_x = wall_t + pi_x0 + mic_x_from_gpio_edge;

    if (mic_port_y_walls) {
        // Clamped away from the -X wall. Centring these on mic_x put
        // their near edge at x = 3.9, leaving a 0.9 mm web against the
        // -X wall's inner face — a single-wall sliver at a 0.4 mm
        // nozzle, visible in the slicer as a thin triangle at the
        // corner and certain to break. 6 mm minimum gives two solid
        // perimeters plus infill.
        y_wall_port_x = max(mic_x - mic_port_w / 2, wall_t + 6);
        // -Y wall
        translate([y_wall_port_x, -0.1, mic_port_z])
            rounded_slot_y(mic_port_w, mic_port_h, mic_port_r, wall_t + 0.2);
        // +Y wall
        translate([y_wall_port_x, outer_w - wall_t - 0.1, mic_port_z])
            rounded_slot_y(mic_port_w, mic_port_h, mic_port_r, wall_t + 0.2);
    }

    if (mic_port_x_wall) {
        // -X wall (GPIO edge) — the PRIMARY opening, because the mics
        // sit only ~10 mm behind it. See the mic_slot_* block above.
        y_lo = base_r + 0.5;           // the corner arc ends at y = base_r
        y_hi = outer_w - y_lo;
        y0 = max(mic_y_a - mic_slot_w / 2, y_lo);   // slot 0 centred on mic A
        n_slots = floor((y_hi - y0 - mic_slot_w) / mic_slot_pitch) + 1;
        for (i = [0 : n_slots - 1])
            translate([-0.1, y0 + i * mic_slot_pitch, mic_slot_z])
                rounded_slot_x(mic_slot_w, mic_slot_h, mic_slot_w / 2,
                               wall_t + 0.2);
    }
}

module snap_bumps_on_base() {
    // Two bumps on each long side of the base, near the top rim.
    // Bumps have a small ramp on top so the lid slides on cleanly.
    z = base_h - snap_bump_z_from_top_of_base;
    // Long walls (parallel to x-axis)
    for (y_side = [0, outer_w])
        for (x = [outer_l * 1/4, outer_l * 3/4])
            translate([x, y_side, z])
                rotate([0, 90, 0])
                    cylinder(h = snap_bump_l, d = 2 * snap_bump_h,
                             center = true);
}

module base() {
    difference() {
        // Solid outer shell
        rbox(outer_l, outer_w, base_h, base_r, c_bot = base_edge_c);
        // Hollow the interior
        translate([wall_t, wall_t, floor_t])
            rbox(inner_l, inner_w, base_h, base_r - wall_t);
        // Cable grommet hole on the +X wall (port side), aligned
        // vertically with the Pi's micro-USB port. The plug inserts
        // into the Pi from the port_x_clear chamber inside the case
        // and the cable exits through this grommet.
        cable_world_y = wall_t + pi_y0 + pi_micro_usb_y_in_pi;
        translate([outer_l - wall_t - 0.1, cable_world_y, floor_t + 10])
            rotate([0, 90, 0])
                cylinder(h = wall_t + 1, d = cable_dia);
        // (v14) LED viewing slit on the -Y wall (next wall clockwise
        // from the +X grommet wall, viewed from above). Also close to
        // the LED corner: the Pi's PWR+ACT LEDs sit near the +X/-Y
        // corner, ~11.5 mm from this wall.
        // Horizontal rectangle 10 mm wide × 2 mm tall, centered
        // laterally on the wall, bottom edge 5 mm from the outer
        // ground (including the floor thickness).
        led_slit_w = 10;   // X-direction (along the wall length)
        led_slit_h = 2;    // Z-direction (top down)
        led_slit_z = 5;    // Bottom edge of slit, from outer ground
        translate([outer_l / 2 - led_slit_w / 2,
                   -0.1,
                   led_slit_z])
            cube([led_slit_w, wall_t + 0.2, led_slit_h]);
        // (v15/v16) Mic openings — see the mic_port_* / mic_slot_*
        // blocks above.
        base_mic_ports();
    }
    // Pi mounting standoffs on the floor
    translate([wall_t, wall_t, floor_t])
        pi_standoffs_group();
    // Snap-fit bumps on outer walls
    snap_bumps_on_base();
}

module speaker_front_mount_cutouts() {
    // Front-mount cutouts through the lid's top face:
    //   - one Ø40 mm sound hole for the driver frame to protrude
    //   - four Ø3.5 mm clearance holes for M3 screws, at the
    //     36×36 mm screw pattern
    // Positioned relative to the caller's translate — normally the
    // center of the lid's top face.
    translate([0, 0, -0.1])
        cylinder(h = lid_top_t + 0.4, d = sp_baffle_cut);
    for (dx = [-sp_screw_pat / 2, sp_screw_pat / 2],
         dy = [-sp_screw_pat / 2, sp_screw_pat / 2])
        translate([dx, dy, -0.1])
            cylinder(h = lid_top_t + 0.4, d = sp_screw_dia);
}

module speaker_mount_bosses() {
    // Four short bosses hanging DOWN from the underside of the lid
    // top face, coaxial with the four screw clearance holes. Each
    // boss adds plastic for the M3 to self-tap into (the 3 mm top
    // face alone is marginal for M3 grip). Screws enter from ABOVE
    // through the flange + top face, then bite into the boss.
    for (dx = [-sp_screw_pat / 2, sp_screw_pat / 2],
         dy = [-sp_screw_pat / 2, sp_screw_pat / 2])
        translate([dx, dy, -sp_boss_h])
            difference() {
                cylinder(h = sp_boss_h, d = sp_boss_dia);
                translate([0, 0, -0.1])
                    cylinder(h = sp_boss_h + 0.2, d = sp_boss_pilot);
            }
}

module lid_snap_recesses() {
    // Matching recesses on the lid's inner wall in the lip section.
    // Lip cavity spans z=0 to z=lid_lip. Snap bump at
    // base's z = base_h - snap_bump_z_from_top_of_base corresponds
    // (after lid slides down over base) to lid's local z =
    // lid_lip - snap_bump_z_from_top_of_base.
    z = lid_lip - snap_bump_z_from_top_of_base;
    // Lid inner-wall coordinates in the lip section
    x_wall_lo = lid_wall - lid_lip_clearance;
    y_wall_lo = lid_wall - lid_lip_clearance;
    // Base outer walls sit at y = y_wall_lo and y = y_wall_lo + outer_w
    for (y = [y_wall_lo, y_wall_lo + outer_w])
        for (x_frac = [1/4, 3/4])
            translate([x_wall_lo + outer_l * x_frac, y, z])
                rotate([0, 90, 0])
                    cylinder(h = snap_bump_l + 2,
                             d = 2 * (snap_bump_h + 0.2),
                             center = true);
}

module lid() {
    union() {
        difference() {
            // Outer lid shell (bigger than base by 2*lid_wall each axis)
            rbox(lid_outer_l, lid_outer_w, lid_h, base_r + lid_wall,
                 c_bot = lid_rim_c, r_top = lid_top_r);
            // Lip cavity — receives base's top rim
            translate([lid_wall - lid_lip_clearance,
                       lid_wall - lid_lip_clearance,
                       -0.1])
                rbox(outer_l + 2 * lid_lip_clearance,
                     outer_w + 2 * lid_lip_clearance,
                     lid_lip + 0.1, base_r + lid_lip_clearance);
            // Interior chamber above the lip — for speaker back +
            // room over the HAT
            translate([lid_wall + wall_t,
                       lid_wall + wall_t,
                       lid_lip])
                rbox(inner_l, inner_w, lid_h - lid_lip - lid_top_t,
                     base_r - wall_t);
            // Speaker front-mount cutouts (Ø40 sound hole + 4 M3
            // clearance holes at 36×36 pattern), centered on the
            // lid's top face.
            translate([lid_outer_l / 2, lid_outer_w / 2,
                       lid_h - lid_top_t])
                speaker_front_mount_cutouts();
            // (v16) The two Ø3 mm mic holes are gone from the top
            // face: they sat ~20 mm off the mics in plan and ~50 mm
            // above them. The base's grille band is the mic path.
            // (v14) LED viewing hole removed from the lid — LEDs are
            // no longer visible from directly above once the speaker
            // is mounted. LED viewing is now via a side-wall slit on
            // the base (+X wall, closest to the Pi's LED corner).
            // Snap-fit recesses
            lid_snap_recesses();
        }
        // Speaker mounting bosses, hanging DOWN from the underside
        // of the top face, coaxial with the 4 clearance holes.
        // Added as union() so they exist as solid material in the
        // interior chamber.
        translate([lid_outer_l / 2, lid_outer_w / 2,
                   lid_h - lid_top_t])
            speaker_mount_bosses();
    }
}

// ===== Layout =====
// Which part(s) to render. Override via CLI:
//   openscad -o base.stl -D 'part="base"' case.scad
//   openscad -o lid.stl  -D 'part="lid"'  case.scad
//   openscad -o both.stl -D 'part="both"' case.scad  (default)
part = "both";

if (part == "base")      base();
else if (part == "lid")  lid();
else {
    base();
    translate([outer_l + 15, 0, 0]) lid();
}
