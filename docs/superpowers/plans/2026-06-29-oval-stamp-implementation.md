# Oval Stamp Head Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a rebuildable SolidWorks 2020 part for a 45 × 30 mm oval stamp head with a 5 mm base and a mirrored 1 mm raised face matching the supplied reference image.

**Architecture:** Build the base as a native SolidWorks extruded ellipse, then import a cleaned, horizontally mirrored vector outline for the face artwork as a second sketch and merge its 1 mm extrusion into the base. Keep the base and artwork as separate features so dimensions and artwork can be edited independently.

**Tech Stack:** SolidWorks 2020, vector outline derived from the supplied JPEG, DXF/DWG sketch import, SolidWorks rebuild and measurement tools

---

## File Structure

- Create: `D:/ai-novel-video-generator/assets/stamp/oval_stamp_face_mirrored.dxf` — cleaned and mirrored closed artwork contours.
- Create: `D:/ai-novel-video-generator/oval_stamp_head.SLDPRT` — editable SolidWorks 2020 part.
- Reference: `C:/Users/11847/Desktop/WhatsApp Image 2026-06-29 at 18.39.17.jpeg` — source artwork.

### Task 1: Prepare the face artwork

- [ ] **Step 1: Inspect the reference at full resolution**

Confirm that the source contains the double oval border, two flowers, and the text “台北市 / 教務處 / 私立再興高級中學”.

- [ ] **Step 2: Isolate the blue artwork**

Convert the blue strokes to a binary mask while removing the white background and isolated scan noise. Preserve the original handwritten forms and spacing.

- [ ] **Step 3: Fit the artwork to the stamp face**

Scale the outermost artwork boundary to fit inside 45 × 30 mm without clipping. Keep a small safety inset from the physical edge and preserve the source aspect ratio.

- [ ] **Step 4: Repair and simplify contours**

Close open contours, remove isolated islands that are not part of the intended artwork, simplify excessive nodes, and ensure printable strokes are approximately 0.4 mm or wider.

- [ ] **Step 5: Mirror and export**

Mirror all artwork horizontally and export closed contours as `D:/ai-novel-video-generator/assets/stamp/oval_stamp_face_mirrored.dxf` using millimetres.

- [ ] **Step 6: Verify the vector file**

Reopen the DXF and confirm the artwork is mirrored, complete, unclipped, and contains no visibly missing characters or border segments.

### Task 2: Build the native SolidWorks base

- [ ] **Step 1: Create the part**

Create a new SolidWorks part and set document units to MMGS.

- [ ] **Step 2: Sketch the outer ellipse**

On the Top Plane, create a centre-point ellipse at the origin. Dimension the major axis to 45 mm and minor axis to 30 mm, with the major axis horizontal.

- [ ] **Step 3: Extrude the base**

Create a 5 mm Boss-Extrude from the ellipse, normal to the sketch plane.

- [ ] **Step 4: Remove the sharp outer edge**

Apply a small chamfer to the rear outer perimeter only, leaving the 45 × 30 mm printing face unchanged.

- [ ] **Step 5: Verify the base**

Rebuild the part and confirm one solid body, a 45 × 30 mm face, and 5 mm base thickness.

### Task 3: Add the raised mirrored face

- [ ] **Step 1: Start the face sketch**

Select the flat printing face and begin a new sketch.

- [ ] **Step 2: Import the DXF**

Insert `D:/ai-novel-video-generator/assets/stamp/oval_stamp_face_mirrored.dxf` into the active sketch at 1:1 millimetre scale, centred on the part origin.

- [ ] **Step 3: Check sketch geometry**

Use SolidWorks sketch diagnostics to locate open endpoints, self-intersections, duplicate entities, and contours that would create zero-thickness geometry. Repair each reported issue before extrusion.

- [ ] **Step 4: Extrude the artwork**

Create a 1 mm Boss-Extrude from all intended border, flower, and text regions. Enable Merge result so the artwork joins the base.

- [ ] **Step 5: Verify rebuild and body count**

Force rebuild and confirm there are no feature errors and exactly one solid body remains.

### Task 4: Inspect and save the deliverable

- [ ] **Step 1: Inspect the face normal to the screen**

Confirm the model face shows the complete source composition in horizontally mirrored form, including both border lines and both flowers.

- [ ] **Step 2: Measure final dimensions**

Confirm the bounding dimensions are 45 × 30 × 6 mm, where the 6 mm total height includes the 1 mm raised artwork.

- [ ] **Step 3: Inspect an isometric view**

Confirm the raised artwork visibly projects from the face and is merged into the base without floating bodies.

- [ ] **Step 4: Save the editable part**

Save as `D:/ai-novel-video-generator/oval_stamp_head.SLDPRT` in SolidWorks 2020 format.

- [ ] **Step 5: Final reopen check**

Close and reopen the saved part, force rebuild, and confirm the model opens without missing-reference or rebuild warnings.

