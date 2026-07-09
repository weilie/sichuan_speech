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
sp_screw_dia  = 3.5;   // M3 clearance through the lid (spec says
                       // Ø3.3 on the flange; 3.5 gives a bit of
                       // slop for print tolerance)

// Speaker is FRONT-mounted (v11): driver drops in from above,
// flange rests on top of the lid, foam gasket compresses against
// the lid's outer surface for an air-tight seal. 4 × M3 screws
// come from above, through the flange holes, through clearance
// holes in the lid, and thread into short bosses on the lid's
// underside.
sp_boss_dia   = 7;     // Boss outer diameter on the lid interior
sp_boss_h     = 5;     // Boss length hanging down from the top face
sp_boss_pilot = 2.5;   // M3 self-tap pilot bore in each boss

mic_dia       = 3;
mic_spacing   = 55;    // Distance between the two HAT mics (approx)

cable_dia     = 9;     // Micro-USB cable + grommet clearance

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
//   inner_l = 56 + 0.5 + 29.5 = 86 mm
//   inner_w = 85 + 0.5 + 0.5  = 86 mm
//   outer   = 92 × 92 mm

// Pi micro-USB port location: on the +X port edge, 10 mm from the
// -Y (SD-card) end. Y-coordinate along the port edge, in Pi-local
// (rotated) coordinates.
pi_micro_usb_y_in_pi = 10;

// Pi 3B LEDs (PWR + ACT) on the top surface, near the -Y (SD-card)
// and +X (port) corner. Pi-local coords in the rotated frame.
pi_led_x_in_pi = 53;   // Near +X port edge (= pi_l - 3)
pi_led_y_in_pi = 11.5; // Near -Y SD-card edge
led_hole_dia  = 5;     // Viewing hole in the lid's top face

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
        // Cable grommet hole on the +X wall (port side), aligned
        // vertically with the Pi's micro-USB port. The plug inserts
        // into the Pi from the port_x_clear chamber inside the case
        // and the cable exits through this grommet.
        cable_world_y = wall_t + pi_y0 + pi_micro_usb_y_in_pi;
        translate([outer_l - wall_t - 0.1, cable_world_y, floor_t + 10])
            rotate([0, 90, 0])
                cylinder(h = wall_t + 1, d = cable_dia);
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

module mic_holes() {
    // HAT sits above Pi with its long axis along case Y (Pi's long
    // axis) and its short axis extending inward from the GPIO edge
    // (case -X). Mics are at the two SHORT ends of the HAT, roughly
    // above where the HAT's front edge meets the ends.
    // Positions computed in base-world coords; the caller shifts
    // by (lid_wall, lid_wall) to place them in lid coords.
    x = wall_t + pi_x0 + 28;       // ~28 mm inward from GPIO edge
    y_center = wall_t + pi_y0 + pi_w / 2;  // Pi Y center
    for (dy = [-mic_spacing / 2, mic_spacing / 2])
        translate([x, y_center + dy, -0.1])
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
            // Speaker front-mount cutouts (Ø40 sound hole + 4 M3
            // clearance holes at 36×36 pattern), centered on the
            // lid's top face.
            translate([lid_outer_l / 2, lid_outer_w / 2,
                       lid_h - lid_top_t])
                speaker_front_mount_cutouts();
            // Mic holes on top face
            translate([lid_wall, lid_wall, lid_h - lid_top_t])
                mic_holes();
            // LED viewing hole on top face
            translate([lid_wall, lid_wall, lid_h - lid_top_t])
                led_hole();
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
