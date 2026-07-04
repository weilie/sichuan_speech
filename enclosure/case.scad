// Sichuan Speech enclosure — v1
//
// Two-piece column: base + lid, snap-fit.
//   base   — houses Pi 3B v1.2 + ReSpeaker 2-Mics HAT V2 stack,
//            cable grommet hole on the back wall
//   lid    — cups over the base; top face holds the Dayton DMA45-4
//            speaker (top-firing) and two 3 mm mic holes above the
//            HAT's mic positions
//
// Iteration policy: place mic hole positions from best guess for v1
// print, then refine after test-fit.

// ----- Board & driver dimensions -----
pi_l          = 85;    // Pi 3B long axis
pi_w          = 56;    // Pi 3B short axis
pi_h_stack    = 34;    // Pi board top-of-tallest-component to floor
                       // + GPIO connector + HAT board thickness.
                       // Give a bit of slack above HAT before lid.
pi_mount_dx   = 58;    // Pi mounting-hole spacing along long axis
pi_mount_dy   = 49;    // Pi mounting-hole spacing along short axis
pi_mount_edge = 3.5;   // Distance from Pi board corners to hole centres
pi_screw_hole = 2.4;   // M2.5 self-tapping into plastic post

sp_flange     = 48;    // Dayton DMA45-4 square flange side
sp_flange_t   = 3;     // Flange thickness
sp_depth      = 25;    // Total driver depth (flange bottom to magnet)
sp_cone_dia   = 42;    // Sound-hole diameter through the lid
sp_screw_dia  = 3.4;   // M3 clearance
sp_screw_pat  = 42;    // Screw pattern (corner-to-corner spacing);
                       // adjust after measuring the flange holes

mic_dia       = 3;
mic_spacing   = 55;    // Distance between the two HAT mics (approx)

cable_dia     = 9;     // Micro-USB cable + grommet clearance

// ----- Enclosure dimensions -----
wall_t        = 3;     // Side-wall thickness
floor_t       = 3;     // Base floor thickness
lid_top_t     = 3;     // Lid top-face thickness
fit_slop      = 2.5;   // Extra clearance per side between Pi and wall
                       // (last print was "a bit tight"; +1 mm over
                       // the 1.5 mm we had implicitly)

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
inner_l = pi_l + 2 * fit_slop;
inner_w = pi_w + 2 * fit_slop;
base_h  = floor_t + pi_h_stack;
outer_l = inner_l + 2 * wall_t;
outer_w = inner_w + 2 * wall_t;

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
    // Pi board sits corner-aligned at (fit_slop, fit_slop) relative
    // to inner cavity. Its mounting holes are pi_mount_edge from each
    // corner of the board.
    x0 = fit_slop + pi_mount_edge;
    y0 = fit_slop + pi_mount_edge;
    for (x = [x0, x0 + pi_mount_dx],
         y = [y0, y0 + pi_mount_dy])
        translate([x, y, 0]) pi_standoff();
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
                    scale([1, 1, 1])
                        cylinder(h = snap_bump_l, d = 2 * snap_bump_h,
                                 center = true);
}

module base() {
    difference() {
        // Solid outer shell
        cube([outer_l, outer_w, base_h]);
        // Hollow the interior
        translate([wall_t, wall_t, floor_t])
            cube([inner_l, inner_w, base_h]);
        // Cable grommet hole on the back wall (short wall at +x end)
        translate([outer_l - wall_t - 0.1, outer_w / 2, floor_t + 10])
            rotate([0, 90, 0])
                cylinder(h = wall_t + 1, d = cable_dia);
    }
    // Pi mounting standoffs on the floor
    translate([wall_t, wall_t, floor_t])
        pi_standoffs_group();
    // Snap-fit bumps on outer long walls
    snap_bumps_on_base();
}

module speaker_cutout() {
    // Round through-hole for the sound cone
    translate([0, 0, -0.1])
        cylinder(h = lid_top_t + 0.2, d = sp_cone_dia);
    // Square flange recess: the flange sits DOWN into a shallow
    // square pocket from below (interior side of the lid). We recess
    // the flange from the underside so the top face of the lid stays
    // flush with the speaker face.
    translate([-sp_flange / 2, -sp_flange / 2, -0.1])
        cube([sp_flange, sp_flange, sp_flange_t + 0.1]);
    // Four screw clearance holes at flange corners (M3)
    for (dx = [-sp_screw_pat / 2, sp_screw_pat / 2],
         dy = [-sp_screw_pat / 2, sp_screw_pat / 2])
        translate([dx, dy, -0.1])
            cylinder(h = lid_top_t + 0.4, d = sp_screw_dia);
}

module mic_holes() {
    // Approximate placement: 55 mm apart, offset toward the back of
    // the enclosure (where the HAT sits over the Pi's GPIO edge).
    y = outer_w * 0.7;
    for (dx = [-mic_spacing / 2, mic_spacing / 2])
        translate([outer_l / 2 + dx, y, -0.1])
            cylinder(h = lid_top_t + 0.4, d = mic_dia);
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
    difference() {
        // Outer lid shell (bigger than base by 2*lid_wall each axis)
        cube([lid_outer_l, lid_outer_w, lid_h]);
        // Lip cavity — receives base's top rim
        translate([lid_wall - lid_lip_clearance,
                   lid_wall - lid_lip_clearance,
                   -0.1])
            cube([outer_l + 2 * lid_lip_clearance,
                  outer_w + 2 * lid_lip_clearance,
                  lid_lip + 0.1]);
        // Interior chamber above the lip — for speaker back +
        // room over the HAT
        translate([lid_wall + wall_t,
                   lid_wall + wall_t,
                   lid_lip])
            cube([inner_l, inner_w, lid_h - lid_lip - lid_top_t]);
        // Speaker cutout on top face (centered)
        translate([lid_outer_l / 2, lid_outer_w / 2,
                   lid_h - lid_top_t])
            speaker_cutout();
        // Mic holes on top face
        translate([lid_wall, lid_wall, lid_h - lid_top_t])
            mic_holes();
        // Snap-fit recesses
        lid_snap_recesses();
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
