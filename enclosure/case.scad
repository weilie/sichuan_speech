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

// Dayton DMA45-4
sp_flange     = 48;    // Square flange side
sp_flange_t   = 3;
sp_depth      = 25;    // Total driver depth
sp_screw_pat  = 42;    // Screw pattern (corner-to-corner) — verify!
sp_dia_cone   = 42;    // Approximate visible cone diameter for
                       // sizing the grille area

// Speaker mounts to the UNDERSIDE of the lid top face via 4 posts
// that hang down from the interior. Screws come from below (through
// the flange holes) into pilot holes in the posts.
post_dia      = 6;     // Post outer diameter
post_h        = 4;     // Post length hanging down from top face
post_pilot    = 2.5;   // M3 self-tapping pilot bore
post_pilot_h  = post_h + 2;  // pilot bore goes into the top face too

// Grille (over the sound-cone area, keeps the driver protected)
grille_dia         = 44;   // Diameter of the grilled area
grille_hole_dia    = 2.5;  // Diameter of individual grille holes
grille_hole_pitch  = 4.0;  // Center-to-center spacing (hex grid)

mic_dia       = 3;
mic_spacing   = 55;    // Distance between the two HAT mics (approx)

cable_dia     = 9;     // Micro-USB cable + grommet clearance

// ----- Enclosure dimensions -----
wall_t        = 3;     // Side-wall thickness
floor_t       = 3;     // Base floor thickness
lid_top_t     = 3;     // Lid top-face thickness
plug_x_clear  = 4.5;   // Clearance between Pi's SD-card short edge
                       // (-X) and the case wall. Widened from a
                       // symmetric 2.5 mm because the micro-USB plug
                       // + cable needs side room on that end.
usb_x_clear   = 0.5;   // Clearance between Pi's USB-stack short edge
                       // (+X) and the case wall. Reduced from 2.5 mm
                       // to donate almost all X slack to the plug
                       // side; the USB stack is internal-only in our
                       // build (no external port access needed).
                       // 0.5 mm is at the edge of what print
                       // tolerance allows — the v2 base showed the
                       // print is accurate enough.
fit_slop      = 2.5;   // Clearance on the +Y (GPIO) side
port_clear    = 20;    // Extra clearance on the -Y (port) side so a
                       // micro-USB plug body can insert into the Pi
                       // without hitting the wall. Makes the
                       // interior asymmetric — Pi sits closer to the
                       // GPIO wall than to the port wall.
target_square = true;  // If true, pad +Y (GPIO side) to make outer
                       // footprint square (matches lid dimensions)

// Pi 3B v1.2 micro-USB port location: on the long "bottom" edge,
// near the left-hand short edge (SD-card side). In Pi-local
// coordinates (Pi origin at 0, 0), the port center is at X ≈ 10 mm.
pi_micro_usb_x_in_pi = 10;

// Pi 3B v1.2 LEDs (PWR red + ACT green) are on the top surface
// near the corner between the port long edge and the SD-card short
// edge. Rough Pi-local center of the two LEDs.
pi_led_x_in_pi = 11.5;
pi_led_y_in_pi = 3;
led_hole_dia  = 5;   // Viewing hole in the lid's top face

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
inner_l = pi_l + plug_x_clear + usb_x_clear;
inner_w_min = pi_w + fit_slop + port_clear;
// If a square outer is requested, pad inner_w up so outer_w == outer_l.
inner_w = target_square ? max(inner_w_min, inner_l) : inner_w_min;
base_h  = floor_t + pi_h_stack;
outer_l = inner_l + 2 * wall_t;
outer_w = inner_w + 2 * wall_t;

// Pi origin (bottom-left corner of the Pi board) in interior coords
// (i.e., relative to inside face of the -X and -Y walls).
pi_x0 = plug_x_clear;
pi_y0 = port_clear;

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
        // Cable grommet hole on the -Y long wall, aligned with the
        // Pi's micro-USB port position. The cable enters through
        // this hole; the actual plug lives inside the enclosure and
        // has port_clear mm of chamber to insert cleanly.
        cable_world_x = wall_t + pi_x0 + pi_micro_usb_x_in_pi;
        translate([cable_world_x, wall_t + 0.1, floor_t + 10])
            rotate([90, 0, 0])
                cylinder(h = wall_t + 1, d = cable_dia);
    }
    // Pi mounting standoffs on the floor
    translate([wall_t, wall_t, floor_t])
        pi_standoffs_group();
    // Snap-fit bumps on outer long walls
    snap_bumps_on_base();
}

module grille_holes() {
    // Hex-packed round holes covering a disc of diameter grille_dia,
    // punched through the lid top face (Z=0..lid_top_t).
    row_dy = grille_hole_pitch * sqrt(3) / 2;
    r = grille_dia / 2;
    nr = ceil(r / row_dy) + 1;
    nc = ceil(r / grille_hole_pitch) + 1;
    for (row = [-nr : nr]) {
        y = row * row_dy;
        x_off = (row % 2 == 0) ? 0 : grille_hole_pitch / 2;
        for (col = [-nc : nc]) {
            x = col * grille_hole_pitch + x_off;
            if (x * x + y * y <= (r - grille_hole_dia / 2) *
                                 (r - grille_hole_dia / 2))
                translate([x, y, -0.1])
                    cylinder(h = lid_top_t + 0.4, d = grille_hole_dia);
        }
    }
}

module speaker_mount_posts() {
    // Four posts hanging DOWN from the interior of the lid top face,
    // at the corners of the speaker's screw pattern. Speaker flange
    // rests against the bottom face of the posts. Screws come from
    // below through the flange hole up into the post's pilot bore.
    // Each post is a solid cylinder with a coaxial pilot hole from
    // its bottom.
    for (dx = [-sp_screw_pat / 2, sp_screw_pat / 2],
         dy = [-sp_screw_pat / 2, sp_screw_pat / 2])
        translate([dx, dy, -post_h])
            difference() {
                cylinder(h = post_h, d = post_dia);
                translate([0, 0, -0.1])
                    cylinder(h = post_pilot_h + 0.1, d = post_pilot);
            }
}

module mic_holes() {
    // Approximate placement: 55 mm apart, offset toward the back of
    // the enclosure (where the HAT sits over the Pi's GPIO edge).
    y = outer_w * 0.7;
    for (dx = [-mic_spacing / 2, mic_spacing / 2])
        translate([outer_l / 2 + dx, y, -0.1])
            cylinder(h = lid_top_t + 0.4, d = mic_dia);
}

module led_hole() {
    // Viewing port for the Pi 3B's PWR + ACT LEDs. Placed in the lid
    // top face directly above their position on the Pi (using base
    // world coords + lid_wall offset). The HAT does not cover this
    // corner of the Pi so the line of sight is clear.
    x = wall_t + pi_x0 + pi_led_x_in_pi;
    y = wall_t + pi_y0 + pi_led_y_in_pi;
    translate([x, y, -0.1])
        cylinder(h = lid_top_t + 0.4, d = led_hole_dia);
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
            // Grille holes over the speaker cone area
            translate([lid_outer_l / 2, lid_outer_w / 2,
                       lid_h - lid_top_t])
                grille_holes();
            // Mic holes on top face
            translate([lid_wall, lid_wall, lid_h - lid_top_t])
                mic_holes();
            // LED viewing hole on top face
            translate([lid_wall, lid_wall, lid_h - lid_top_t])
                led_hole();
            // Snap-fit recesses
            lid_snap_recesses();
        }
        // Speaker mounting posts, hanging DOWN from the underside
        // of the top face. Added as union() so they exist as solid
        // material inside the interior chamber (opposite of a hole).
        translate([lid_outer_l / 2, lid_outer_w / 2,
                   lid_h - lid_top_t])
            speaker_mount_posts();
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
