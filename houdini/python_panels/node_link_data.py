"""
node_link_data.py — Houdini 公式ドキュメントのノード一覧（ページ名と表示名）。自動生成。手で直さない。

生成: houdini/update_node_links.py（2026-11-17）。元: https://www.sidefx.com/docs/houdini/nodes/<章>/index.html の一覧に載っているリンクだけ。
形: 章ごとに、1 行 = 「ページ名|表示名」。URL は  BASE/<章>/<ページ名>.html  （名前空間つきは  apex--名前  のように -- でつながる）。
"""

CHECKED_ON = "2026-11-17"
BASE = "https://www.sidefx.com/docs/houdini/nodes"

NODES = {
    "sop": """\
Labs--polyscalpel-1.0|Labs PolyScalpel
_onnx_dtype_common|_onnx_dtype_common
_onnx_rgba_treatment_common|_onnx_rgba_treatment_common
adaptiveprune|Adaptive Prune
add|Add
agent|Agent
agentaddmldeformer|Agent Add ML Deformer
agentclip|Agent Clip
agentclipproperties|Agent Clip Properties
agentcliptransitiongraph|Agent Clip Transition Graph
agentcollisionlayer|Agent Collision Layer
agentconfigurejoints|Agent Configure Joints
agentconstraintnetwork|Agent Constraint Network
agentdefinitioncache|Agent Definition Cache
agentedit|Agent Edit
agentlayer|Agent Layer
agentlookat|Agent Look At
agentmetadata|Agent Metadata
agentprep|Agent Prep
agentproxy|Agent Proxy
agentrelationship|Agent Relationship
agentterrainadaptation|Agent Terrain Adaptation
agenttransformgroup|Agent Transform Group
agentunpack|Agent Unpack
agentvellumunpack|Agent Vellum Unpack
alembic|Alembic
alembicgroup|Alembic Group
alembicprimitive|Alembic Primitive
align|Spline Align
apex--addcharacterpicker|APEX Add Character Picker
apex--addgroom|APEX Add Groom
apex--addmldeformer|APEX Add ML Deformer
apex--addwrinkles|APEX Add Wrinkles
apex--animationfromskeleton|APEX Animation from Skeleton
apex--autorigbuilder|APEX AutoRig Builder
apex--autorigcomponent|APEX AutoRig Component
apex--buildfkgraph|APEX Build FK Graph
apex--channelconvert|APEX Channel Convert
apex--channelprimitivesfrommotionclip|Channel Primitives from MotionClip
apex--configurecharacter|APEX Configure Character
apex--configurecontrols|APEX Configure Controls
apex--configuregraph|APEX Configure Graph
apex--controlextract|APEX Control Extract
apex--controlupdateparms|APEX Control Update Parms
apex--graph|APEX Graph
apex--invokegraph|APEX Invoke Graph
apex--layoutgraph|APEX Layout Graph
apex--mapcharacter|APEX Map Character
apex--mergegraph|APEX Merge Graph
apex--packcharacter|APEX Pack Character
apex--rigmerge|APEX Rig Merge
apex--rigparent|APEX Rig Parent
apex--rigpose|APEX Rig Pose
apex--sceneaddanimation|APEX Scene Add Animation
apex--sceneaddcamera|APEX Scene Add Camera
apex--sceneaddcharacter|APEX Scene Add Character
apex--sceneaddprop|APEX Scene Add Prop
apex--sceneanimate|APEX Scene Animate
apex--scenecopyanimation|APEX Scene Copy Animation
apex--sceneimportanimation|APEX Scene Import Animation
apex--sceneinvoke|APEX Scene Invoke
apex--scenemerge|APEX Scene Merge
apex--script|APEX Script
apex--unpackcharacter|APEX Unpack Character
armaturecapture|Armature Capture
armaturedeform|Armature Deform
assemble|Assemble
associationselect|Association Select
attribadjustarray|Attribute Adjust Array
attribadjustcolor|Attribute Adjust Color
attribadjustdict|Attribute Adjust Dictionary
attribadjustfloat|Attribute Adjust Float
attribadjustinteger|Attribute Adjust Integer
attribadjustvector|Attribute Adjust Vector
attribblur|Attribute Blur
attribcast|Attribute Cast
attribcombine|Attribute Combine
attribcomposite|Attribute Composite
attribcopy|Attribute Copy
attribcreate|Attribute Create
attribdelete|Attribute Delete
attribexpression|Attribute Expression
attribfade|Attribute Fade
attribfill|Attribute Fill
attribfrommap|Attribute from Map
attribfromparm|Attribute from Parameters
attribfrompieces|Attribute From Pieces
attribfromvolume|Attribute from Volume
attribinterpolate|Attribute Interpolate
attribmirror|Attribute Mirror
attribnoise|Attribute Noise
attribpaint|Attribute Paint
attribpromote|Attribute Promote
attribrandomize|Attribute Randomize
attribremap|Attribute Remap
attribreorient|Attribute Reorient
attribsort|Attribute Sort
attribstringedit|Attribute String Edit
attribswap|Attribute Swap
attribtransfer|Attribute Transfer
attribtransferbyuv|Attribute Transfer by UV
attribute|Attribute Rename
attribvop|Attribute VOP
attribwrangle|Attribute Wrangle
bakegsplat|Bake GSplats
bakeode|Bake ODE
bakepreprocess|Bake Pre-Process
bakevolume|Bake Volume
ballisticpath|Ballistic Path
basis|Spline Basis
bend|Bend
blast|Blast
blastbyattribute|Blast by Attribute
blendshapes|Blend Shapes
block_begin|Block Begin
block_end|Block End
bonecapturebiharmonic|Bone Capture Biharmonic
bonecapturelines|Bone Capture Lines
bonedeform|Bone Deform
bonelink|Bone Link
boolean|Boolean
booleanfracture|Boolean Fracture
bound|Bound
box|Box
bulge|Bulge
cache|Cache
cacheif|Cache If
camera|Camera
cameraedit|Camera Edit
camerafrompoints|Camera from Points
cameraimport|Camera Import
cameratopoints|Camera To Points
cap|Spline Cap
capture|Bone Capture
captureattribpack|Capture Attribute Pack
captureattribunpack|Capture Attribute Unpack
capturecorrect|Capture Correct
capturelayerpaint|Capture Layer Paint
capturemirror|Capture Mirror
captureoverride|Capture Override
captureproximity|Bone Capture Proximity
carve|Carve
chain|Chain
channel|Channel
circle|Circle
circlefromedges|Circle from Edges
circlespline|Circle Spline
clay|Spline Clay
clean|Clean
clip|Clip
clothcapture|Cloth Capture
clothdeform|Cloth Deform
cloudadjustdensityprofile|Cloud Adjust Density Profile
cloudbillowynoise|Cloud Billowy Noise
cloudclip|Cloud Clip
cloudlight|Cloud Light
cloudnoise|Cloud Noise
cloudshapefromintersection|Cloud Shape from Intersection
cloudshapefromline|Cloud Shape from Line
cloudshapefrompolygon|Cloud Shape from Polygon
cloudshapegenerate|Cloud Shape Generate
cloudshapereplicate|Cloud Shape Replicate
cloudwispynoise|Cloud Wispy Noise
cluster|Cluster
clusterpoints|Cluster Points
collisiondetectcl|Collision Detect CL
collisionsource|Collision Source
color|Color
comb|Comb
compile_begin|Block Begin Compile
compile_end|Block End Compile
connectadjacentpieces|Connect Adjacent Pieces
connectivity|Connectivity
control|Control
convert|Convert
convertheightfield|Convert HeightField
convertline|Convert Line
convertmeta|Convert Meta
convertvdb|Convert VDB
convertvdbpoints|Convert VDB Points
convertvolume|Convert Volume
convexdecomposition|Convex Decomposition
copnet|COP Network
coppreviewmaterial|COP Preview Material
copytocurves|Copy to Curves
copytopoints|Copy to Points
copyxform|Copy and Transform
crease|Crease
creep|Spline Creep
cregion|Capture Region
crosssectionsurface|Cross Section Surface
crowdassignlayers|Crowd Assign Layers
crowdmotionpath|Crowd MotionPath
crowdmotionpatharcinglayer|Crowd MotionPath Arcing Layer
crowdmotionpathavoid|Crowd MotionPath Avoid
crowdmotionpathedit|Crowd MotionPath Edit
crowdmotionpathevaluate|Crowd MotionPath Evaluate
crowdmotionpathfollow|Crowd MotionPath Follow
crowdmotionpathlayer|Crowd MotionPath Layer
crowdmotionpathretime|Crowd MotionPath Retime
crowdmotionpathtransition|Crowd MotionPath Transition
crowdmotionpathtrigger|Crowd MotionPath Trigger
crowdsource|Crowd Source
curve|Curve
curveanimate|Curve Animate
curveclay|Spline Curve Clay
curvesect|Curve Intersect
debrissource|Debris Source
deflate|Deflate
deformationwrangle|Deformation Wrangle
delete|Delete
deltamush|DeltaMush
dembones_skinningconverter|Dem Bones Skinning Converter
detangle|Detangle
dissolve|Dissolve
distancealonggeometry|Distance along Geometry
distancefromgeometry|Distance from Geometry
distancefromtarget|Distance from Target
divide|Divide
dopimport|DOP Import
dopimportfield|DOP Import Fields
dopimportrecords|DOP Import Records
dopnet|DOP Network
drawcurve|Draw Curve
each|Each
edgecollapse|Edge Collapse
edgecusp|Edge Cusp
edgedivide|Edge Divide
edgeequalize|Edge Equalize
edgeflip|Edge Flip
edgefracture|Edge Fracture
edgerelax|Edge Relax
edgestraighten|Edge Straighten
edgetransport|Edge Transport
edit|Edit
ends|Ends
enumerate|Enumerate
enumeratepairs|Enumerate Pairs
error|Error
explodedview|Exploded View
exportobjtransforms|Export Object Transforms
extractcentroid|Extract Centroid
extractcontours|Extract Contours
extractpointfromcurve|Extract Point from Curve
extracttpose|Extract T-Pose
extracttransform|Extract Transform
extrude|Extrude
extrudevolume|Extrude Volume
facet|Facet
featherbarbtangents|Feather Barb Tangents
featherbarbxform|Feather Barb Transform
featherclump|Feather Clump
featherdeform|Feather Deform
featherdeintersect|Feather Deintersect
featherinstancepool|Feather Instance Pool
feathermatchuncondensed|Feather Match Uncondensed
feathermindist|Feather Minimum Distance
feathernoise|Feather Noise
feathernormalize|Feather Normalize
featherprimitive|Feather Primitive
featherray|Feather Ray
featherresample|Feather Resample
feathershapeorg|Feather Shape Organize
feathersurface|Feather Surface
feathersurfaceblend|Feather Surface Blend
feathertemplateassign|Feather Template Assign
feathertemplatefromshape|Feather Template from Shape
feathertemplateinterpolate|Feather Template Interpolate
featheruncondense|Feather Uncondense
featherutility|Feather Utility
feathervisualize|Feather Visualize
featherwidth|Feather Width
femdeform|FEM Deform
femvalidate|FEM Validate
femvisualize|FEM Visualize
fibergroom|Fiber Groom
filament_advect_pos|Filament Advect
file|File
filecache|File Cache
filemerge-2.0|File Merge
fillet|Spline Fillet
findinstances|Find Instances
findshortestpath|Find Shortest Path
fit|Spline Fit
flatten|Flatten
flipboundary|FLIP Boundary
flipcollide|FLIP Collide
flipcontainer|FLIP Container
flipsolver|FLIP Solver
flipsource|FLIP Source
flipvolumecombine|FLIP Volume Combine
fluidcompress|Fluid Compress
font|Font
force|Force
fractal|Fractal
frankenmuscle|Franken Muscle
frankenmusclepaint|Franken Muscle Paint
fur|Fur
fuse|Fuse
gltf|glTF 2.0
gluecluster|Glue Cluster
grainsource|Grain Source
graphcolor|Graph Color
grid|Grid
groomblend|Groom Blend
groomfetch|Groom Fetch
groomswitch|Groom Switch
groupbylasso|Group by Lasso
groupcombine|Group Combine
groupcopy|Group Copy
groupcreate|Group
groupdelete|Group Delete
groupexpand|Group Expand
groupexpression|Group Expression
groupfindpath|Group Find Path
groupfromattribboundary|Group from Attribute Boundary
groupinvert|Group Invert
grouppaint|Group Paint
grouppromote|Group Promote
grouprange|Group Range
grouprename|Group Rename
groupsfromname|Groups from Name
grouptransfer|Group Transfer
guideadvect|Guide Advect
guideclumpcenter|Guide Clump Center
guidecollidevdb|Guide Collide With VDB
guidedeform|Guide Deform
guidedraw|Draw Guides
guidefill|Guide Fill
guidefindstrays|Guide Find Strays
guidegroom|Guide Groom
guidegroup|Guide Group
guideinit|Guide Initialize
guideinterpolationmesh|Guide Interpolation Mesh
guidemask|Guide Mask
guidepartition|Guide Partition
guideprocess|Guide Process
guidereduce|Guide Reduce
guideskinattriblookup|Guide Skin Attribute Lookup
guidesurface|Guide Surface
guidetangentspace|Guide Tangent Space
guidetransfer|Guide Transfer
guideutility|Guide Utility
guidevolume|Guide Volume
haircardgen|Hair Card Generate
hairclump|Hair Clump
hairgen|Hair Generate
hairgrowthfield|Hair Growth Field
heatgeodesic|Heat Geodesic
heightfield|HeightField
heightfield_blur|HeightField Blur
heightfield_clip|HeightField Clip
heightfield_copylayer|HeightField Copy Layer
heightfield_crop|HeightField Crop
heightfield_cutoutbyobject|HeightField Cutout by Geometry
heightfield_deform|HeightField Deform
heightfield_distort|HeightField Distort by Noise
heightfield_distortbylayer|HeightField Distort by Layer
heightfield_drawmask|HeightField Draw Mask
heightfield_erode|HeightField Erode
heightfield_erode_hydro|HeightField Erode Hydro
heightfield_erode_precipitation|HeightField Erode Precipitation
heightfield_erode_thermal|HeightField Erode Thermal
heightfield_file|HeightField File
heightfield_flatten|HeightField Flatten
heightfield_flowfield|HeightField Flow Field
heightfield_isolatelayer|HeightField Isolate Layer
heightfield_layer|HeightField Layer
heightfield_layerclear|HeightField Layer Clear
heightfield_layerproperty|HeightField Layer Properties
heightfield_maskbyfeature|HeightField Mask by Feature
heightfield_maskbyobject|HeightField Mask by Geometry
heightfield_maskbyocclusion|HeightField Mask by Occlusion
heightfield_noise|HeightField Noise
heightfield_output|HeightField Output
heightfield_paint|HeightField Paint
heightfield_patch|HeightField Patch
heightfield_pattern|HeightField Pattern
heightfield_project|HeightField Project
heightfield_quickshade|HeightField Quick Shade
heightfield_remap|HeightField Remap
heightfield_resample|HeightField Resample
heightfield_scatter|HeightField Scatter
heightfield_slump|HeightField Slump
heightfield_terrace|HeightField Terrace
heightfield_tilesplice|HeightField Tile Splice
heightfield_tilesplit|HeightField Tile Split
heightfield_visualize|HeightField Visualize
heightfield_xform|HeightField Transform
hole|Hole
implicitsurface|Implicit Surface
implicitsurface_convert|Implicit Surface Convert
implicitsurface_doctor|Implicit Surface Doctor
implicitsurface_eval|Implicit Surface Evaluate
implicitsurface_operation|Implicit Surface Operation
implicitsurface_slice|Implicit Surface Slice
implicitsurface_velocity|Implicit Surface Velocity
inflate|Inflate
instance|Instance
intersectionanalysis|Intersection Analysis
intersectionstitch|Intersection Stitch
invoke|Invoke Compiled Block
invokegraph|Invoke Compiled Graph
isooffset|IsoOffset
join|Join
kinefx--adapttoterrain|Adapt to Terrain
kinefx--agentanimationunpack|Agent Animation Unpack
kinefx--agentcharacterunpack|Agent Character Unpack
kinefx--agentfromrig|Agent from Rig
kinefx--agentposefromrig|Agent Pose from Rig
kinefx--attachjointgeo|Attach Joint Geometry
kinefx--attribtransformcompute|Attribute Transform Compute
kinefx--attribtransformextract|Attribute Transform Extract
kinefx--biped_retarget|Biped Retarget
kinefx--biped_setup|Biped Setup
kinefx--capturepackedgeo|Capture Packed Geometry
kinefx--characterblendshapechannels|Character Blend Shape Channels
kinefx--characterblendshapes|Character Blend Shapes
kinefx--characterblendshapesadd|Character Blend Shapes Add
kinefx--characterblendshapesextract|Character Blend Shapes Extract
kinefx--characterio|Character I/O
kinefx--characterpack|Character Pack
kinefx--characterunpack|Character Unpack
kinefx--computerigpose|Compute Rig Pose
kinefx--computetransform|Compute Transform
kinefx--configureclipinfo|Configure Clip Info
kinefx--configurejointlimits|Configure Joint Limits
kinefx--configurejoints|Configure Joints
kinefx--configurerigvis|Configure Rig Vis
kinefx--deletejoints|Delete Joints
kinefx--dembones_skinningconverter|Dem Bones Skinning Converter
kinefx--dynamicwarp|Dynamic Warp
kinefx--extractlocomotion|Extract Locomotion
kinefx--fbikconfiguretargets|FBIK Configure Targets
kinefx--fbxanimimport|FBX Animation Import
kinefx--fbxcharacterimport|FBX Character Import
kinefx--fbxskinimport|FBX Skin Import
kinefx--fktransfer|FK Transfer
kinefx--fullbodyik|Full Body IK
kinefx--gltfanimimport|GLTF Animation Import
kinefx--gltfcharacterimport|GLTF Character Import
kinefx--gltfskinimport|GLTF Skin Import
kinefx--groupjoints|Group Joints
kinefx--ikchains|IK Chains
kinefx--jointcapturebiharmonic|Joint Capture Biharmonic
kinefx--jointcaptureproximity|Joint Capture Proximity
kinefx--jointdeform|Joint Deform
kinefx--mappoints|Map Points
kinefx--mocapimport|Mocap Import
kinefx--mocapstream|Mocap Stream
kinefx--motionclip|MotionClip
kinefx--motionclipblend|MotionClip Blend
kinefx--motionclipcycle|MotionClip Cycle
kinefx--motionclipevaluate|MotionClip Evaluate
kinefx--motionclipextract|MotionClip Extract
kinefx--motionclipextractkeyposes|MotionClip Extract Key Poses
kinefx--motionclipextractlocomotion|MotionClip Extract Locomotion
kinefx--motionclipposedelete|MotionClip Pose Delete
kinefx--motionclipposeinsert|MotionClip Pose Insert
kinefx--motionclipretime|MotionClip Retime
kinefx--motionclipsequence|MotionClip Sequence
kinefx--motionclipupdate|MotionClip Update
kinefx--motionmixer|Motion Mixer
kinefx--motionmixerfetch|Motion Mixer Fetch
kinefx--orientjoints|Orient Joints
kinefx--parentjoints|Parent Joints
kinefx--pendulummotion|Pendulum Motion
kinefx--posedifference|Pose Difference
kinefx--projectilemotion|Projectile Motion
kinefx--ragdollcollisionshapes|Ragdoll Collision Shapes
kinefx--ragdollsolver|Ragdoll Solver
kinefx--reversefoot|Reverse Foot
kinefx--rigattribvop|Rig Attribute VOP
kinefx--rigattribwrangle|Rig Attribute Wrangle
kinefx--rigcopytransforms|Rig Copy Transforms
kinefx--rigdoctor|Rig Doctor
kinefx--rigmatchpose|Rig Match Pose
kinefx--rigmirrorpose|Rig Mirror Pose
kinefx--rigpose|Rig Pose
kinefx--rigpython|Rig Python
kinefx--rigstashpose|Rig Stash Pose
kinefx--rop_fbxanimoutput|ROP FBX Animation Output
kinefx--rop_fbxcharacteroutput|ROP FBX Character Output
kinefx--rop_gltfcharacteroutput|ROP GLTF Character Output
kinefx--scenecharacterexport|Scene Character Export
kinefx--scenecharacterimport|Scene Character Import
kinefx--secondarymotion|Secondary Motion
kinefx--skeleton|Skeleton
kinefx--skeletonblend|Skeleton Blend
kinefx--skeletonmirror|Skeleton Mirror
kinefx--smoothmotion|Smooth Motion
kinefx--stabilizejoint|Stabilize Joint
kinefx--usdanimimport|UsdSkel Animation Import
kinefx--usdcharacterimport|UsdSkel Character Import
kinefx--usdskinimport|UsdSkel Skin Import
kinefx--visrig|Visualize Rig
labs--2d_wavefunctioncollapse|Labs 2D Wave Function Collapse (Solver)
labs--align_and_distribute-2.0|Labs Align and Distribute
labs--attribute_normalize_float-1.0|Labs Attribute Normalize Float
labs--attribute_normalize_vector-1.0|Labs Attribute Normalize Vector
labs--attribute_value_replace|Labs Attribute Value Replace
labs--automatic_trim_texture|Labs Automatic Trim Texture
labs--autouv-1.0|Labs Auto UV
labs--av_analyze_images-7.0|Labs AV Analyze Images
labs--av_depth_map-7.0|Labs AV Depth Map
labs--av_initialize-7.0|Labs AV Initialize
labs--av_meshing-7.0|Labs AV Meshing
labs--av_photogrammetry-7.0|Labs AV Photogrammetry
labs--av_structure_from_motion-7.0|Labs AV Structure from Motion
labs--av_texturing-7.0|Labs AV Texturing
labs--biome_attributes_evolve-1.1|Labs Biome Attributes Evolve
labs--biome_attributes_to_terrain-1.1|Labs Biome Attributes to Terrain
labs--biome_configure|Labs Biome Configure
labs--biome_configure_multibiomes|Labs Biome Configure Multibiomes
labs--biome_curve_label-1.1|Labs Biome Curve Label
labs--biome_define-1.0|Labs Biome Define
labs--biome_definitions_file-1.0|Labs Biome Definitions File
labs--biome_plant_define-1.3|Labs Biome Plant Define
labs--biome_plant_definitions_file-1.3|Labs Biome Plant Definitions File
labs--biome_plant_scatter-1.3|Labs Biome Plant Scatter
labs--biome_region_assign-1.2|Labs Biome Region Assign
labs--boolean_curve-1.0|Labs Boolean Curve
labs--box_clip|Labs Box Clip
labs--boxcutter-1.0|Labs Boxcutter
labs--building_from_patterns-1.1|Labs Building from Patterns
labs--building_generator-4.0|Labs Building Generator
labs--building_generator_utility-2.0|Labs Building Generator Utility
labs--cable_generator-2.1|Labs Cable Generator
labs--calculate_slope|Labs Calculate Slope
labs--calculate_thickness-1.0|Labs Calculate Thickness
labs--calculate_uv_distortion-1.0|Labs Calculate UV Distortion
labs--capsule-1.0|Labs Capsule
labs--chaotic_shapes-1.0|Labs Chaotic Shapes
labs--clean_seams-1.0|Labs Clean Seams
labs--cluster_refine-1.0|Labs Cluster Refine
labs--color_blend-1.0|Labs Color Blend
labs--connect_polygon_neighbours-1.0|Labs Connect Polygon Neighbours
labs--connectivity_and_segmentation-1.0|Labs Connectivity and Segmentation
labs--cook_with_timeout-1.0|Labs Cook with Timeout
labs--copy_points-1.0|Labs Copy Points
labs--curve_branches|Labs Curve Branches
labs--curve_resample_by_density-1.0|Labs Curve Resample by Density
labs--cut_hole-1.0|Labs Cut Hole
labs--cylinder_generator-2.0|Labs Cylinder
labs--decal_projector-1.1|Labs Decal Projector
labs--delete_mismatched_attributes_and_groups-1.0|Labs Delete Mismatched Attributes and Groups
labs--delete_small_parts-1.2|Labs Delete Small Parts
labs--delight|Labs Delight
labs--delight_gsplats|Labs Delight GSplats
labs--destruction_cleanup-2.0|Labs Destruction Cleanup
labs--detail_mesh-1.1|Labs Detail Mesh
labs--dirtskirt-1.0|Labs Dirt Skirt
labs--disc_generator-1.1|Labs Disc
labs--dissolve_flat_edges-1.0|Labs Dissolve Flat Edges
labs--distance_from_border|Labs Distance From Border
labs--edge_damage-2.1|Labs Edge Damage
labs--edge_smooth-1.0|Labs Edge Smooth
labs--edgegroup_to_curve-1.1|Labs Edge Group To Curve
labs--export_uv_wireframe-1.0|Labs Export UV Wireframe
labs--extract_borders|Labs Extract Borders
labs--extract_filename|Labs Extract Filename
labs--extract_silhouette-1.0|Labs Extract Silhouette
labs--fast_gaussian_curvature-1.0|Labs Fast Gaussian Curvature
labs--fast_group_unshared-1.0|Labs Fast Group Unshared
labs--fast_remesh-1.1|Labs Fast Remesh
labs--fbx_archive_import|Labs FBX Archive Import
labs--filecache-2.0|Labs File Cache
labs--flowmap-2.0|Labs Flowmap
labs--flowmap_guide|Labs Flowmap Guide
labs--flowmap_obstacle-3.0|Labs Flowmap Obstacle
labs--flowmap_to_color|Labs Flowmap to Color
labs--flowmap_visualize|Labs Flowmap Visualize
labs--goz_export|Labs GoZ Export
labs--goz_import|Labs GoZ Import
labs--group_by_attribute|Labs Group by Attribute
labs--group_by_measure|Labs Group by Measure
labs--group_curve_corners-1.0|Labs Group Curve Corners
labs--hexagon_grid-1.0|Labs Hexagon Grid
labs--hf_combine_masks|Labs HF Combine Masks
labs--hf_insert_mask|Labs HF Insert Mask
labs--houdini_icon|Labs Houdini Icon
labs--impostor_baker-1.1|Labs Impostor Baker
labs--inside_face_uvs-1.0|Labs Inside Face UVs
labs--instance_attributes-1.0|Labs Instance Attributes
labs--kelvin_wakes_deformer-1.0|Kelvin Wakes Deformer
labs--lightning|Labs Lightning
labs--lod_create-2.0|Labs LOD Create
labs--loop_volume-1.0|Labs Loop Volume
labs--loops_from_selection-1.0|Labs Loops from Selection
labs--lot_subdivision-2.0|Labs Lot Subdivision
labs--make_loop-2.1|Labs Make Loop
labs--mandelbulb_generator-1.1|Labs Mandelbulb
labs--maps_baker-5.0|Labs Maps Baker
labs--material_to_override-1.0|Labs Material to Override
labs--measure_curvature-3.2|Labs Measure Curvature
labs--merge_small_islands|Labs Merge Small Islands
labs--merge_splines-1.0|Labs Merge Splines
labs--mesh_sharpen|Labs Mesh Sharpen
labs--mesh_slice|Labs Mesh Slice
labs--mesh_tiler-1.0|Labs Mesh Tiler
labs--min_max_average-1.0|Labs Min Max Average
labs--ml_cv_directory_import-1.0|Labs ML CV Directory Import
labs--ml_cv_keypoint_metadata-1.0|Labs ML CV Keypoint Metadata
labs--ml_cv_label_metadata-1.0|Labs ML CV Label Metadata
labs--ml_cv_promote_synth_attribute-1.0|Labs ML CV Promote Synth Attribute
labs--ml_cv_rop_annotation_output-1.0|Labs ML CV ROP Annotation Output
labs--ml_cv_texture_mask-1.0|Labs ML CV Texture Mask
labs--ml_cv_vector_data-1.0|Labs ML CV Vector Data
labs--ml_cv_visualize_keypoints-1.0|Labs ML CV Visualize Keypoints
labs--multi_attribute_promote-1.0|Labs Multi Attribute Promote
labs--multi_bounding_box|Labs Multi Bounding Box
labs--name_from_capture_weight-1.0|Labs Name from Capture Weight
labs--niagara|Labs Niagara ROP
labs--normals_from_gsplats|Labs Normals from GSplats
labs--obj_importer|Labs OBJ Importer
labs--osm_buildings|Labs OSM Buildings
labs--osm_filter|Labs OSM Filter
labs--osm_import|Labs OSM Import
labs--path_deform|Labs Path Deform
labs--pathfinding_global-1.0|Labs Pathfinding Global
labs--pcg_export-1.0|Labs PCG Export
labs--physical_ambient_occlusion-1.1|Labs Physical Ambient Occlusion
labs--physics_painter|Labs Physics Painter
labs--pick_and_place|Labs Pick and Place
labs--points_grid-1.0|Labs Points Grid
labs--polydeform|Labs PolyDeform
labs--polyslice-1.2|Labs PolySlice
labs--polywire_uv-1.1|Labs PolyWire UV
labs--post_anim_deform-1.0|Labs Post Animation Deform
labs--procedural_smoke|Labs Procedural Smoke
labs--progressive_resample|Labs Progressive Resample
labs--quad_sphere_generator-1.1|Labs Quad Sphere
labs--quadrangulate-2.0|Labs Quadrangulate
labs--quick_basic_tree|Labs Quick Basic Tree
labs--quickmaterial-2.2|Labs Quick Material
labs--radial_sort-1.1|Labs Radial Sort
labs--random_selection-1.1|Labs Random Selection
labs--rbd_edge_strip|Labs RBD Edge Strip
labs--regions_from_image-1.1|Labs Regions from Image
labs--remove_inside_faces|Labs Remove Inside Faces
labs--remove_uv_distortion-1.0|Labs Remove UV Distortion
labs--repair-1.0|Labs Repair
labs--rizomuv_optimize-1.0|Labs RizomUV Optimize
labs--rizomuv_processor-1.0|Labs RizomUV Processor
labs--rizomuv_rectangularize-1.0|Labs RizomUV Rectangularize
labs--rizomuv_unwrap-1.0|Labs RizomUV Unwrap
labs--road_generator|Labs Road Generator
labs--rop_zibravdb_compress-1.0|Labs ZibraVDB Compress
labs--scifi_panels|Labs SciFi Panels
labs--settlement_connections-1.0|Labs Settlement Connections
labs--simple_baker-2.0|Labs Simple Baker
labs--simple_retime-1.0|Labs Simple Retime
labs--simple_rope_wrap-1.0|Labs Simple Rope Wrap
labs--simple_shapes-2.0|Labs Simple Shapes
labs--sine_wave|Labs Sine Wave
labs--sketchfab_output|Labs Sketchfab
labs--skinning_converter-3.0|Labs Skinning Converter
labs--snow_buildup-2.0|Labs Snow Buildup
labs--soften_normals|Labs Soften Normals
labs--spectral_feature_extract-1.0|Labs Spectral Feature Extract
labs--splatter|Labs Splatter
labs--split_by_expression-1.0|Labs Split by Expression
labs--split_prim_by_normal-1.0|Labs Split Primitives by Normal
labs--static_fracture_export|Labs Static Fracture Export
labs--straight_skeleton_2D|Labs Straight Skeleton 2D
labs--straight_skeleton_3d|Labs Straight Skeleton 3D
labs--straighten-1.0|Labs Straighten
labs--substance_material|Labs Substance Material
labs--superformula_shapes-1.0|Labs Superformula Shapes
labs--terrain_analysis-1.0|Labs Terrain Analysis
labs--terrain_layer_export|Labs Terrain Layer Export
labs--terrain_layer_import|Labs Terrain Layer Import
labs--terrain_segment-1.0|Labs Terrain Mesh ROP
labs--terrain_texture-1.0|Labs Terrain Texture ROP
labs--testgeometry_luiz|Labs Test Geometry: Luiz
labs--testgeometry_paul|Labs Test Geometry: Paul
labs--texel_density-1.1|Labs Texel Density
labs--thicken-1.1|Labs Thicken
labs--trace_psd_file-3.0|Labs Trace PSD File
labs--tree_branch_generator-|Labs Tree Branch Generator
labs--tree_branch_generator-1.2|Labs Tree Branch Generator
labs--tree_branch_placer-1.1|Labs Tree Branch Placer
labs--tree_controller-|Labs Tree Controller
labs--tree_controller-1.1|Labs Tree Controller
labs--tree_hierarchy-1.0|Labs Tree Hierarchy
labs--tree_leaf_generator|Labs Tree Leaf Generator
labs--tree_simple_leaf|Labs Tree Simple Leaf
labs--tree_trunk_generator-|Labs Tree Trunk Generator
labs--tree_trunk_generator-1.1|Labs Tree Trunk Generator
labs--trim_texture|Labs Trim Texture
labs--trim_texture_utility|Labs Trim Texture Utility
labs--triplanar_displace|Labs Triplanar Displace
labs--turntable|Labs Turntable
labs--udim_tile_number-1.0|Labs UDIM Tile Number
labs--unreal_groom_export-1.0|Labs Unreal Groom Export
labs--unreal_pivotpainter-1.1|Labs Unreal Pivot Painter
labs--unreal_spline-1.0|Labs Unreal Spline
labs--unreal_worldcomposition_prepare|Labs Unreal Worldcomposition Prepare
labs--uv_remove_overlap-1.0|Labs UV Remove Overlap
labs--uv_transfer-1.1|Labs UV Transfer
labs--uv_unitize-1.1|Labs UV Unitize
labs--uv_unwrap_cylinder-1.0|Labs UV Unwrap Cylinder
labs--validate_geometry_type-1.0|Labs Validate Geometry Type
labs--vdb_transform_properties-1.0|Labs VDB Transform Properties
labs--vector_field|Labs Vector Field Export
labs--view_vertex_order-1.0|Labs View Vertex Order
labs--visualize_uvs-2.1|Labs UV Visualize
labs--visualize_vector-1.0|Labs Visualize Vector
labs--volume_adjust_look-1.0|Labs Volume Adjust Look
labs--volume_texture-1.0|Labs VolumeTexture Export
labs--wang_tiles_decoder|Labs Wang Tiles Decoder
labs--wang_tiles_sample|Labs Wang Tiles Sample
labs--wfc_initialize|Labs WFC Initialize Grid
labs--wfc_sample_paint|Labs WFC Sample Paint
labs--workitem_import|Labs PDG Work-Item Import
labs--zibravdb_decompress-1.0|Labs ZibraVDB Decompress
labs--zibravdb_filecache-1.0|Labs ZibraVDB File Cache
laplacian|Laplacian
lattice|Lattice Deform
latticefromvolume|Lattice from Volume
lidarimport|Lidar Import
line|Line
linearreduce|Linear Reduce
linearsolver|Linear Solver
lopimport|LOP Import
lsystem|L-System
magnet|Magnet
maskbyfeature|Mask by Feature
matchaxis|Match Axis
matchsize|Match Size
matchtopology|Match Topology
material|Material
mdd|MDD
measure|Measure
measurethickness|Measure Thickness
merge|Merge
mergepacked|Merge Packed
metaball|Metaball
metagroups|MetaGroups
mirror|Mirror
ml_attribgenerate|ML Attribute Generate
ml_deform|ML Deform
ml_example|ML Example
ml_exampledecompose|ML Example Decompose
ml_exampleimport|ML Example Import
ml_examplepartition|ML Example Partition
ml_extractexample|ML Extract Example
ml_posedeserialize|ML Pose Deserialize
ml_posegenerate|ML Pose Generate
ml_poseserialize|ML Pose Serialize
ml_regressioninference|ML Regression Inference
ml_regressionkernel|ML Regression Kernel
ml_regressionlinear|ML Regression Linear
ml_regressionproximity|ML Regression Proximity
ml_volumetilecomponent|ML Volume Tile Component
ml_volumetileinference|ML Volume Tile Inference
ml_volumeupres|ML Volume Upres
mpmcollider|MPM Collider
mpmcontainer|MPM Container
mpmdebrissource|MPM Debris Source
mpmdeformpieces|MPM Deform Pieces
mpmpostfracture|MPM Post-Fracture
mpmsolver|MPM Solver
mpmsource|MPM Source
mpmsurface|MPM Surface
muscleadjustvolume|Muscle Adjust Volume
muscleautotensionlines|Muscle Auto Tension Lines
muscleconstraintpropertiesotis|Muscle Constraint Properties Otis
muscleconstraintpropertiesvellum|Muscle Constraint Properties Vellum
muscledeform|Muscle Deform
muscledeintersect|Muscle Deintersect
muscleflex|Muscle Flex
muscleid|Muscle ID
musclemerge|Muscle Merge
musclemirror|Muscle Mirror
musclepaint|Muscle Paint
musclepreroll|Muscle Preroll
muscleproperties|Muscle Properties Vellum
musclepropertiesotis|Muscle Properties Otis
musclesolidify|Muscle Solidify
musclesolvervellum|Muscle Solver Vellum
muscletensionlines|Muscle Tension Lines
muscletensionlinesactivate|Muscle Tension Lines Activate
muscletransfer|Muscle Transfer
name|Name
neighborsearchcl|Neighbor Search CL
neuralpointsurface|Neural Point Surface
neuralterraingenerate|Neural Terrain Generate
normal|Normal
null|Null
object_merge|Object Merge
oceanevaluate|Ocean Evaluate
oceanfoam|Ocean Foam
oceansource|Ocean Source
oceanspectrum|Ocean Spectrum
oceanwaves|Ocean Waves
onnx|ONNX Inference
opencl|OpenCL
orientalongcurve|Orientation along Curve
otisconfiguremuscleandtissue|Otis Muscle and Tissue Configure
otissolver|Otis Solver
output|Output
pack|Pack
packeddiskedit|Packed Disk Properties
packededit|Packed Properties
packedfoldercopy|Packed Folder Copy
packedfoldersplit|Packed Folder Split
packfolder|Pack Folder
packgroom|Groom Pack
packinject|Pack Inject
packpoints|Pack Points
paintcolorvolume|Paint Color Volume
paintfogvolume|Paint Fog Volume
paintsdfvolume|Paint SDF Volume
particlefluidsurface|Particle Fluid Surface
particlefluidtank|Particle Fluid Tank
particletrail|Particle Trail
pathdeform|Path Deform
pca|Principal Component Analysis
peak|Peak
planarinflate|Planar Inflate
planarpatch|Planar Patch
planarpatchfromcurves|Planar Patch from Curves
planarpleat|Planar Pleat
planartiles|Planar Tiles
platonic|Platonic Solids
pointcapture|Point Capture
pointcloudiso|Point Cloud Iso
pointcloudmeasure|Point Cloud Measure
pointcloudnormal|Point Cloud Normal
pointcloudreduce|Point Cloud Reduce
pointcloudsurface|Point Cloud Surface
pointdeform|Point Deform
pointgenerate|Point Generate
pointjitter|Point Jitter
pointreplicate|Point Replicate
pointsfromvolume|Points from Volume
pointvelocity|Point Velocity
pointweld|Point Weld
polybevel|PolyBevel
polybridge|Poly Bridge
polycut|PolyCut
polydoctor|PolyDoctor
polyexpand2d|Poly Expand 2D
polyextrude|Poly Extrude
polyfill|PolyFill
polyframe|PolyFrame
polyhinge|PolyHinge
polyloft|PolyLoft
polypatch|PolyPatch
polypath|PolyPath
polyreduce|PolyReduce
polysoup|PolySoup
polyspline|PolySpline
polysplit|PolySplit
polywire|PolyWire
posescope|Pose Scope
posespacedeform|Pose-Space Deform
posespacedeformcombine|Pose-Space Deform Combine
posespaceedit|Pose-Space Edit
posespaceeditconfigure|Pose-Space Edit Configure
primitive|Primitive Properties
profile|Spline Profile
project|Spline Project
proximity|Proximity
pyrobakevolume|Pyro Bake Volume
pyroburstsource|Pyro Burst Source
pyropostprocess|Pyro Post-Process
pyroscatterfromburst|Pyro Scatter from Burst
pyrosolver|Pyro Solver
pyrosource|Pyro Source
pyrosourceinstance|Pyro Source Instance
pyrosourcepack|Pyro Source Pack
pyrosourcespread|Pyro Source Spread
pyrospawnsources|Pyro Spawn Sources
pyrothrusterexhaust|Pyro Thruster Exhaust
pyrotrailpath|Pyro Trail Path
pyrotrailsource|Pyro Trail Source
python|Python
pythonsnippet|Python Snippet
quadremesh|Quad Remesh
quadspinner--gaea_terrain_color_visualizer-1.0|Gaea Terrain Color Visualizer
quadspinner--gaea_terrain_processor-1.0|Gaea Terrain Processor
rails|Rails
rawimport|Raw Import
ray|Ray
rbdbulletsolver|RBD Bullet Solver
rbdcardeform|RBD Car Deform
rbdcarfollowpath|RBD Car Follow Path
rbdcarfracture|RBD Car Fracture
rbdcarrig|RBD Car Rig
rbdcartransform|RBD Car Transform
rbdcluster|RBD Cluster
rbdconetwistconstraintproperties|RBD Cone Twist Constraint Properties
rbdconfigure|RBD Configure
rbdconnectedfaces|RBD Connected Faces
rbdconstraintproperties|RBD Constraint Properties
rbdconstraintsfromcurves|RBD Constraints From Curves
rbdconstraintsfromlines|RBD Constraints From Lines
rbdconstraintsfromrules|RBD Constraints From Rules
rbdconvertconstraints|RBD Convert Constraints
rbddeformingtoanimated|RBD Deforming to Animated
rbddeformpieces|RBD Deform Pieces
rbddisconnectedfaces|RBD Disconnected Faces
rbdexplodedview|RBD Exploded View
rbdfindinstances|RBD Find Instances
rbdgroupconstraints|RBD Group Constraints
rbdguidesetup|RBD Guide Setup
rbdinteriordetail|RBD Interior Detail
rbdio|RBD I/O
rbdmatchtransforms|RBD Match Transforms
rbdmaterialfracture|RBD Material Fracture
rbdpack|RBD Pack
rbdpaint|RBD Paint
rbdunpack|RBD Unpack
rbdxform|RBD Transform
refine|Refine
reguide|Reguide
relax|Point Relax
remesh|Remesh
remeshbubbles|Remesh Bubbles
remeshgrid|Remesh to Grid
remeshtocamera|Remesh to Camera
repack|Repack
resample|Resample
rest|Rest Position
retime|Retime
reverse|Reverse
revolve|Revolve
rewire|Rewire Vertices
ripple-2.0|Ripple
ripplesolver|Ripple Solver
rishader|RMan Shader
roommapframe|Room Map Frame
rop_alembic|Alembic ROP output driver
rop_fbx|Filmbox FBX ROP output driver
rop_geometry|ROP Geometry Output
rop_geometryraw|ROP Geometry Raw Output
rop_gltf|glTF ROP output driver 2.0
rop_ml_exampleraw|rop_ml_exampleraw
round|Spline Round
sblend|Sequence Blend
scatter|Scatter
scatteralign|Scatter and Align
scatterintexturemask|Scatter in Texture Mask
script|Script
sculpt|Sculpt
separatepieces|Separate Pieces
settpose|Set T-Pose
shallowwatersolver|Shallow Water Solver
shapediff|Shape Diff
shotsculpt|Shot Sculpt
shrinkwrap|Shrinkwrap
skin|Skin
skindeform|Skin Deform
skinproperties|Skin Properties
skinsolidify|Skin Solidify
skinsolvervellum|Skin Solver Vellum
skybox|Sky Box
skyfield|Sky Field
skyfieldfrommap|Sky Field from Map
skyfieldnoise|Sky Field Noise
skyfieldpattern|Sky Field Pattern
smooth|Smooth
softpeak|Soft Peak
softxform|Soft Transform
solver|Solver
sort|Sort
sphere|Sphere
spiral|Spiral
split|Split
splitbypointattrib|Split by Point Attribute
splitpoints|Point Split
spraypaint|Spray Paint
sprite|Sprite
starburst|Starburst
stash|Stash
stitch|Stitch
stroke|Stroke
subdivide|Subdivide
subnet|Subnetwork
superquad|Super Quad
surfacedeform|Surface Deform
surfsect|Spline Surfsect
sweep|Sweep
switch|Switch
switchif|Switch-If
tableimport|Table Import
tangentfield|Tangent Field
testgeometry_capybara|Test Geometry: Capybara
testgeometry_crag|Test Geometry: Crag
testgeometry_electra|Test Geometry: Electra
testgeometry_otto|Test Geometry: Otto
testgeometry_pighead|Test Geometry: Pig Head
testgeometry_rubbertoy|Test Geometry: Rubber Toy
testgeometry_shaderball|Test Geometry: Shader Ball
testgeometry_squab|Test Geometry: Squab
testgeometry_templatebody|Test Geometry: Template Body
testgeometry_templatehead|Test Geometry: Template Head
testgeometry_tommy|Test Geometry: Tommy
testsim_crowdtransition|Test Simulation: Crowd Transition
testsim_ragdoll|Test Simulation: Ragdoll
tetconform|Tet Conform
tetembed|Tet Embed
tetfracture|Solid Fracture
tetpartition|Tet Partition
tetrasurface|Convert Tets
texture|UV Texture
texturefeature|Texture Feature
textureopticalflow|Texture Optical Flow
timeshift|TimeShift
tissueproperties|Tissue Properties Vellum
tissuepropertiesotis|Tissue Properties Otis
tissuesolidify|Tissue Solidify Vellum
tissuesolidifyotis|Tissue Solidify Otis
tissuesolvervellum|Tissue Solver Vellum
toonshaderattribs|Toon Shader Attributes
topnet|TOP Geometry
topnetmgr|TOP Network
topobuild|TopoBuild
topoflow|Topo Flow
topoflowsample|Topo Flow Sample
topolandmark|Topo Landmark
toposlidebycurverefs|Topo Slide by Curve References
topotransfer|Topo Transfer
torus|Torus
trace|Trace
trail|Trail
triangulate2d|Triangulate 2D
tribez|Tri Bezier
tridivide|TriDivide
trim|Spline Trim
tube|Tube
udimlist|UDIM List
unix|Unix Command
unpack|Unpack
unpackfolder|Unpack Folder
unpackgroom|Groom Unpack
unpackpoints|Unpack Points
unpackusd|Unpack USD
unpaste|Unpaste
unsubdivide|Unsubdivide
usdapexsceneimport|USD APEX Scene Import
usdconfigure|USD Configure Import
usdconfigureprimsfrompoints|USD Configure Prims from Points
usdcreatecomponent|USD Create Component
usdcreateproxygeometry|USD Create Proxy Geometry
usdexport|USD File Export
usdimport|USD File Import
usdparentgeometry|USD Parent Geometry
usdpointinstancerimport|USD PointInstancer Import
uvautoseam|UV Auto Seam
uvbrush|UV Brush
uvedit|UV Edit
uvflatten|UV Flatten
uvflattenfrompoints|UV Flatten from Points
uvfuse|UV Fuse
uvlayout|UV Layout
uvpelt|UV Pelt
uvproject|UV Project
uvquickshade|UV Quick Shade
uvrelax|UV Relax
uvtransform|UV Transform
uvunwrap|UV Unwrap
vdb|VDB
vdbactivate|VDB Activate
vdbactivatesdf|VDB Activate SDF
vdbadvectpoints|VDB Advect Points
vdbadvectsdf|VDB Advect
vdbanalysis|VDB Analysis
vdbclip|VDB Clip
vdbcollider|VDB Collider
vdbcombine|VDB Combine
vdbconvexclipsdf|VDB Convex Clip SDF
vdbdiagnostics|VDB Diagnostics
vdbextrapolate|VDB Extrapolate
vdbfracture|VDB Fracture
vdbfromparticlefluid|VDB from Particle Fluid
vdbfromparticles|VDB from Particles
vdbfrompolygons|VDB from Polygons
vdbimplicitclipsdf|VDB Implicit Clip SDF
vdblod|VDB LOD
vdbmerge|VDB Merge
vdbmorphsdf|VDB Morph SDF
vdbocclusionmask|VDB Occlusion Mask
vdbpointsdelete|VDB Points Delete
vdbpointsgroup|VDB Points Group
vdbpotentialflow|VDB Potential Flow
vdbprojectnondivergent|VDB Project Non-Divergent
vdbrasterizefrustum|VDB Rasterize Frustum
vdbrenormalizesdf|VDB Renormalize SDF
vdbresample|VDB Resample
vdbreshapesdf|VDB Reshape SDF
vdbsegmentbyconnectivity|VDB Segment by Connectivity
vdbsmooth|VDB Smooth
vdbsmoothsdf|VDB Smooth SDF
vdbtopologytosdf|VDB Topology to SDF
vdbtospheres|VDB to Spheres
vdbvectormerge|VDB Vector from Scalar
vdbvectorsplit|VDB Vector Split
vdbvisualizetree|VDB Visualize Tree
vellumattachconstraints|Vellum Attach Constraints
vellumbrush|Vellum Brush
vellumconfiguremuscles|Vellum Configure Muscles
vellumconfiguretissue|Vellum Configure Tissue
vellumconstraintproperty|Vellum Constraint Properties
vellumconstraints|Vellum Constraints
vellumconstraints_grain|Vellum Configure Grain
vellumdrape|Vellum Drape
vellumio|Vellum I/O
vellumpack|Vellum Pack
vellumpostprocess|Vellum Post-Process
vellumrefframe|Vellum Reference Frame
vellumrestblend|Vellum Rest Blend
vellumsolver|Vellum Solver
vellumunpack|Vellum Unpack
vellumxformpieces|Vellum Transform Pieces
verify_bsdf|Verify BSDF
visibility|Visibility
visualize|Visualize Properties
volume|Volume
volumeadjustfog|Volume Adjust Fog
volumeambientocclusion|Volume Ambient Occlusion
volumeanalysis|Volume Analysis
volumearrivaltime|Volume Arrival Time
volumeblur|Volume Blur
volumebound|Volume Bound
volumebreak|Volume Break
volumecombine|Volume Combine
volumecompress|Volume Compress
volumeconvolve3|Volume Convolve 3×3×3
volumedeform|Volume Deform
volumefeather|Volume Feather
volumefft|Volume FFT
volumefromattrib|Volume from Attribute
volumemerge|Volume Merge
volumemix|Volume Mix
volumenoisefog|Volume Noise Fog
volumenoisesdf|Volume Noise SDF
volumenoisevector|Volume Noise Vector
volumenormalize|Volume Normalize Weights
volumeopticalflow|Volume Optical Flow
volumepatch|Volume Patch
volumeramp|Volume Ramp
volumerasterize|Volume Rasterize
volumerasterizeattributes|Volume Rasterize Attributes
volumerasterizecurve|Volume Rasterize Curve
volumerasterizehair|Volume Rasterize Hair
volumerasterizelattice|Volume Rasterize Lattice
volumerasterizeparticles|Volume Rasterize Particles
volumerasterizepoints|Volume Rasterize Points
volumereduce|Volume Reduce
volumeresample|Volume Resample
volumeresize|Volume Resize
volumesdf|Volume SDF
volumeslice|Volume Slice
volumesplice|Volume Splice
volumestamp|Volume Stamp
volumesurface|Volume Surface
volumetrail|Volume Trail
volumevectorjoin|Volume Vector Join
volumevectorsplit|Volume Vector Split
volumevelocity|Volume Velocity
volumevelocityfromcurves|Volume Velocity from Curves
volumevelocityfromsurface|Volume Velocity from Surface
volumevisualization|Volume Visualization
volumevop|Volume VOP
volumewrangle|Volume Wrangle
voronoiadjacency|Voronoi Adjacency
voronoifracture|Voronoi Fracture
voronoifracturepoints|Voronoi Fracture Points
voronoisplit|Voronoi Split
vortexforceattribs|Vortex Force Attributes
walkonsurface|Walk on Surface
weightarraybiharmonic|Weight Array Biharmonic
weightarrayinterpolate|Weight Array Interpolate
whitewaterpostprocess|Whitewater Post-Process
whitewatersolver|Whitewater Solver
whitewatersource|Whitewater Source
windingnumber|Winding Number
wire|Wireframe
wireblend|Wire Blend
wirecapture|Wire Capture
wiredeform|Wire Deform
wiretransfershape|Wire Transfer
wrinkledeformer|Wrinkle Deformer
xform|Transform
xformaxis|Transform Axis
xformbyattrib|Transform By Attribute
xformpieces|Transform Pieces
""",
    "dop": """\
activevalue|Active Value
affector|Affector
agentarcingcliplayer|Agent Arcing Clip Layer
agentcliplayer|Agent Clip Layer
agentlookat|Agent Look At
agentlookatapply|Agent Look At Apply
agentterrainadaptation|Agent Terrain Adaptation
agentterrainprojection|Agent Terrain Projection
anchoralignaxis|Anchor: Align Axis
anchorobjpointgrouppos|Anchor: Object Point Group Position
anchorobjpointgrouprot|Anchor: Object Point Group Rotation
anchorobjpointidpos|Anchor: Object Point Id Position
anchorobjpointidrot|Anchor: Object Point Id Rotation
anchorobjpointnumpos|Anchor: Object Point Number Position
anchorobjpointnumrot|Anchor: Object Point Number Rotation
anchorobjprimpos|Anchor: Object Primitive Position
anchorobjspacepos|Anchor: Object Space Position
anchorobjspacerot|Anchor: Object Space Rotation
anchorobjsurfacepos|Anchor: Object Surface Position
anchorworldspacepos|Anchor: World Space Position
anchorworldspacerot|Anchor: World Space Rotation
applydata|Apply Data
applyrel|Apply Relationship
blendfactor|Blend Factor
blendsolver|Blend Solver
bulletdata|Bullet Data
bulletrbdsolver|Bullet Solver
bulletsoftconrel|Bullet Soft Constraint Relationship
buoyancyforce|Buoyancy Force
clothconfigureobject|Cloth Configure Object
clothgeometry|clothgeometry
clothmassproperties|Cloth Mass Properties
clothmaterial|Cloth Material
clothmaterialbehavior|Cloth Material Behavior
clothobject|Cloth Object
clothplasticityproperties|Cloth Plasticity Properties
clothsolver|Cloth Solver
clothsolver-|Cloth Solver
clothsolver-2.0|Cloth Solver
clothstitchconstraint|Cloth Stitch Constraint
clothtargetproperties|Cloth Target Properties
clothvisualization|Cloth Visualization
clothvolumecollider|Cloth/Volume Collider
colliderel|Collide Relationship
colliderlabel|Collider Label
conetwistconrel|Cone Twist Constraint Relationship
conrelationship|Constraint Relationship
constraint|Constraint
constraintnetwork|Constraint Network
constraintnetworkrelationship|Constraint Network Relationship
constraintnetworkvisualization|Constraint Network Visualization
container|Container
copydata|Copy Data
copyobject|Copy Objects
copyobjectinfo|Copy Object Information
copysolver|Copy Data Solver
crowdfuzzylogic|Crowd Fuzzy Logic
crowdobject|Crowd Object
crowdsolver|Crowd Solver
crowdstate|Crowd State
crowdtransition|Crowd Transition
crowdtrigger|Crowd Trigger
crowdtriggerlogic|Crowd Trigger Logic
delete|Delete
drag|Drag Force
dragproperties|Drag Properties
embeddingproperties|Embedding Properties
emptydata|Empty Data
emptyobject|Empty Object
emptyrel|Empty Relationship
enablesolver|Enable Solver
fan|Fan Force
femattachconstraint|FEM Attach Constraint
femfuseconstraint|FEM Fuse Constraint
femhybridconfigureobject|Hybrid Configure Object
femhybridobject|FEM Hybrid Object
femregionconstraint|FEM Region Constraint
femslideconstraint|FEM Slide Constraint
femsolidconfigureobject|Solid Configure Object
femsolidobject|FEM Solid Object
femsolver|FEM Solver
femtargetconstraint|FEM Target Constraint
feoutputattributes|Finite Element Output Attributes
fetchdata|Fetch Data
fieldforce|Field Force
filamentobject|Filament Object
filamentsolver|Filament Solver
file|File
filedata|File Data
finiteelementsolver-|FEM Solver
flipconfigureobject|FLIP Configure Object
flipobject|FLIP fluid object
flipsolver|FLIP Solver
fluidconfigureobject|Fluid Configure Object
fluidforce|Fluid Force
fluidobject|Fluid Object
fluidsolver|Fluid Solver
gasadaptiveviscosity|Gas Adaptive Viscosity
gasadvect|Gas Advect
gasadvectcl|Gas Advect CL
gasadvectfield|Gas Advect Field
gasanalysis|Gas Analysis
gasattribswap|Gas Attribute Swap
gasaxisforce|Gas Axis Force
gasblenddensity|Gas Blend Density
gasblur|Gas Blur
gasbuildcollisionmask|Gas Build Collision Mask
gasbuildcollisionmaskfrompieces|Gas Build Collision Mask From Pieces
gasbuildoccupancymask|Gas Build Occupancy Mask
gasbuildrelationshipmask|Gas Build Relationship Mask
gasbuoyancy|Gas Buoyancy
gasburn|Gas Burn
gascalculate|Gas Calculate
gascollisiondetect|Gas Collision Detect
gascombustion|Gas Combustion
gasconvexclipsdf|Gas Convex Clip SDF
gascorrectbymarkers|Gas Correct By Markers
gascross|Gas Cross
gascurveforce|Gas Curve Force
gasdamp|Gas Damp
gasdiffuse|Gas Diffuse
gasdissipate|Gas Dissipate
gasdisturb|Gas Disturb
gaseachdatasolver|Gas Each Data Solver
gasembedfluid|Gas Embed Fluid
gasenforceboundary|Gas Enforce Boundary
gasequalizedensity|Gas Equalize Density
gasequalizevolume|Gas Equalize Volume
gaserror|Gas Error
gasexternalforces|Gas External Forces
gasextrapolate|Gas Extrapolate
gasfeatherfield|Gas Feather Field
gasfeedback|Gas Feedback
gasfetchfieldstoembed|Gas Fetch Fields to Embed
gasfieldtoparticle|Gas Field to Particle
gasfieldvop|Gas Field VOP
gasfieldwrangle|Gas Field Wrangle
gasfilterhourglassmodes|Gas Filter Hourglass Modes
gasgeometrydefragment|Gas Geometry Defragment
gasgeometryoptiontransfer|Gas Geometry/Option Transfer
gasgeometrytosdf|Gas Geometry to SDF
gasguidingvolume|Gas Guiding Volume
gasimpacttoattributes|Gas Impact to Attributes
gasintegrateshallowwaterequations|Gas Integrate Shallow Water Equations
gasintegrator|Gas Integrator
gasinterleavesolver|Gas Interleave Solver
gasintermittentsolve|Gas Intermittent Solve
gaslimit|Gas Limit
gaslimitparticles|Gas Limit Particles
gaslinearcombination|Gas Linear Combination
gaslocalsharpen|Gas Local Sharpen
gaslookup|Gas Lookup
gasmatchfield|Gas Match Field
gasnetfetchdata|Gas Net Fetch Data
gasnetfieldborderexchange|Gas Net Field Border Exchange
gasnetfieldsliceexchange|Gas Net Field Slice Exchange
gasnetslicebalance|Gas Net Slice Balance
gasnetsliceexchange|Gas Net Slice Exchange
gasopencl|Gas OpenCL
gasopenclenforceboundary|Gas OpenCL Enforce Boundary
gasopenclmergevdb|Gas OpenCL Merge VDB
gasparticlecount|Gas Particle Count
gasparticlefluiddensitycl|Particle Fluid Density CL
gasparticlefluidforcescl|Particle Fluid Forces CL
gasparticlemovetoiso|Gas Particle Move to Iso
gasparticleseparate|Gas Particle Separate
gasparticletofield|Gas Particle to Field
gasparticletosdf|Gas Particle to SDF
gasprojectnondivergent|Gas Project Non Divergent
gasprojectnondivergentadaptive|Gas Project Non Divergent Adaptive
gasprojectnondivergentmultigrid|Gas Project Non Divergent Multigrid
gasprojectnondivergentvariational|Gas Project Non Divergent Variational
gasreduce|Gas Reduce
gasreducelocal|Gas Reduce Local
gasreinitializesdf|Gas Reinitialize SDF
gasremap|Gas Remap
gasrepeatsolver|Gas Repeat Solver
gasresetinactive|Gas Reset Inactive
gasresizefield|Gas Resize Field
gasresizefluiddynamic|Gas Resize Fluid Dynamic
gasrest|Gas Rest
gassandforces|Gas Sand Forces
gassdftofog|Gas SDF to Fog
gasseedfluidparticles|Gas Seed Fluid Particles
gasseedmarkers|Gas Seed Markers
gasseedparticles|Gas Seed Particles
gasseedvolume|Gas Volume
gasshred|Gas Shred
gasslicetoindexfield|Gas Slice To Index Field
gasstickoncollision|Gas Stick on Collision
gasstrainforces|Gas Strain Forces
gasstrainintegrate|Gas Strain Integrate
gassubstep|Gas SubStep
gassurfacesnap|Gas Surface Snap
gassurfacetension|Gas Surface Tension
gassynchronizefields|Gas Synchronize Fields
gastargetforce|Gas Target Force
gastemperatureupdate|Gas Temperature Update
gasturbulence|Gas Turbulence
gasupres|Gas Up Res
gasvelocityscale|Gas Velocity Scale
gasvelocitystretch|Gas Velocity Stretch
gasviscosity|Gas Viscosity
gasvolumeramp|Gas Volume Ramp
gasvortexboost|Gas Vortex Boost
gasvortexconfinement|Gas Vortex Confinement
gasvortexequalizer|Gas Vortex Equalizer
gasvorticleforces|Gas Vorticle Forces
gasvorticlegeometry|Gas Vorticle Geometry
gasvorticlerecycle|Gas Vorticle Recycle
gaswavelets|Gas Wavelets
gaswind|Gas Wind
geometrycopy|Geometry Copy
geometryvop|Geometry VOP
geometrywrangle|Geometry Wrangle
glueconrel|Glue Constraint Relationship
gravity|Gravity Force
groundplane|Ground Plane
group|Group
grouprel|Group Relationship
hardconrel|Hard Constraint Relationship
impactanalysis|Impact Analysis
impulseforce|Impulse Force
indexfield|Index Field
indexfieldvisualization|Index Field Visualization
initialoverlaprel|Initial Overlap Relationship
instancedobject|Instanced Object
intangiblevalue|Intangible Value
linktosourceobject|Link to Source Object
magnetforce|Magnet Force
mask|Mask Field
matrixfield|Matrix Field
matrixfieldvisualization|Matrix Field Visualization
merge|Merge
modifydata|Modify Data
motion|Motion
multifieldvisualization|Multi Field Visualization
multisolver|Multiple Solver
muscleupdatevellum|Muscle Update Vellum
netfetchdata|Net Fetch Data
nocollider|No Collider
noconrel|No Constraint Relationship
noise|Noise Field
null|Null
objpos|OBJ Position
onlyonce|Data Only Once
output|ROP Output
particlefieldvisualization|Particle Fluid Visualization
partition|Partition
physparms|Physical Parameters
pointcollider|Point Collider
pointforce|Point Force
pointpos|Point Position
popadvectbyfilaments|POP Advect by Filaments
popadvectbyvolumes|POP Advect by Volumes
popattract|POP Attract
popattribblur|POP Attribute Blur
popattribfromvolume|POP Attribute from Volume
popawaken|POP Awaken
popaxisforce|POP Axis Force
popcollisionbehavior|POP Collision Behavior
popcollisiondetect|POP Collision Detect
popcollisionignore|POP Collision Ignore
popcolor|POP Color
popcurveforce|POP Curve Force
popcurveincompressibleflow|POP Curve Incompressible Flow
popdrag|POP Drag
popdragspin|POP Drag Spin
popfan|POP Fan Cone
popfireworks|POP Fireworks
popfloatbyvolumes|POP Float by Volumes
popflock|POP Flock
popfluid|POP Fluid
popforce|POP Force
popgrains|POP Grains
popgroup|POP Group
pophairinternalforce|POP Hair Internal Force
popinstance|POP Instance
popinteract|POP Interact
popkill|POP Kill
poplimit|POP Limit
poplocalforce|POP Local Force
poplocation|POP Location
poplookat|POP Lookat
popmaskfromshadow|POP Mask from Shadow
popmetaballforce|POP Metaball Force
popobject|POP Object
popproperty|POP Properties
popproximity|POP Proximity
popreplicate|POP Replicate
popsoftlimit|POP Soft Limit
popsolver|POP Solver
popsource|POP Source
popspeedlimit|POP Speed Limit
popspin|POP Spin
popspinbyvolumes|POP Spin by Volumes
popsprite|POP Sprite
popsteeralign|POP Steer Align
popsteeravoid|POP Steer Avoid
popsteercohesion|POP Steer Cohesion
popsteercustom|POP Steer Custom
popsteerobstacle|POP Steer Obstacle
popsteerpath|POP Steer Path
popsteerseek|POP Steer Seek
popsteerseparate|POP Steer Separate
popsteersolver|POP Steer Solver
popsteerturnconstraint|POP Steer Turn Constraint
popsteerwander|POP Steer Wander
popstream|POP Stream
poptorque|POP Torque
popvelocity|POP Velocity
popvop|POP VOP
popwind|POP Wind
popwindshadow|POP Wind Shadow
popwrangle|POP Wrangle
position|Position
pumprel|Pump Relationship
pyrosolver_sparse|Pyro Solver (Sparse)
rbdangularconstraint|RBD Angular Constraint
rbdangularspringconstraint|RBD Angular Spring Constraint
rbdautofreeze|RBD Auto Freeze
rbdcarfollowpath|RBD Car Follow Path
rbdconetwistconstraint|Cone Twist Constraint
rbdconfigureobject|RBD Configure Object
rbdfracturedobject|RBD Fractured Object
rbdguide|RBD Guide
rbdhingeconstraint|RBD Hinge Constraint
rbdkeyactive|RBD Keyframe Active
rbdobject|RBD Object
rbdpackedobject|RBD Packed Object
rbdpinconstraint|RBD Pin Constraint
rbdpointobject|RBD Point Object
rbdreplicator|RBD Replicator
rbdsliderconstraint|Slider Constraint
rbdsolver|RBD Solver
rbdspringconstraint|RBD Spring Constraint
rbdstate|RBD State
rbdvisualization|RBD Visualization
referenceframeforce|Reference Frame Force
renderparmsvolatile|Rendering Parameters Volatile
rigidbodysolver|Rigid Body Solver
rippleconfigureobject|Ripple Configure Object
rippleobject|Ripple Object
ripplesolver|Ripple Solver
rop-dop|ROP Output Driver
rop_dop|ROP Output Driver
sbdconstraint|Soft Body (SBD) Constraint
sbdpinconstraint|Soft Body (SBD) Pin Constraint
sbdspringconstraint|Soft Body (SBD) Spring Constraint
scalarfield|Scalar Field
scalarfieldvisualization|Scalar Field Visualization
scriptsolver|Script Solver
seamproperties|Seam Properties
shellmassproperties|Shell Mass Properties
sinkrel|Sink Relationship
slicealongline|Slice Along Line
sliceplane|Slice by Plane
sliderconrel|Slider Constraint Relationship
smokeobject_sparse|Smoke Object (Sparse)
smokesolver_sparse|Smoke Solver (Sparse)
softattachconrel|Soft Attach Constraint Relationship
softbodycollisionproperties|Soft Body Collision Properties
softbodyfractureproperties|Soft Body Fracture Properties
softbodymaterialbehavior|Soft Body Material Properties
softbodyplasticityproperties|Soft Body Fracture Properties
softbodyrestproperties|Soft Body Rest Properties
softbodysolver|Soft Body Solver
softbodytargetproperties|Soft Body Target Properties
solidanisoproperties|Solid Aniso Multiplier
solidmassproperties|Solid Mass Properties
solidmodeldata|Solid Model Data
solidsolver-|Solid Solver
solidsolver-2.0|Solid Solver
solidvisualization|Solid Visualization
sopgeo|SOP Geometry
sopguide|SOP Guide
sopmergefield|SOP Merge Field
sopscalarfield|SOP Scalar Field
sopsolver|SOP Solver
sopvectorfield|SOP Vector Field
sourcefilaments|Filament Source
sourcerel|Source Relationship
sphereedgetree|Sphere Edge Tree
spherepointtree|Sphere Point Tree
split|Split Object
springconrel|Spring Constraint Relationship
standard_clothobjectattribs|standard_clothobjectattribs
standard_embedding_parms|standard_embedding_parms
standard_feoutputattributes_parms|standard_feoutputattributes_parms
standard_solidobjectattribs|standard_solidobjectattribs
staticobject|Static Object
staticsolver|Static Solver
staticvisualization|Static Visualization
subnet|Subnetwork
surfacecollisionparms|Surface Collision Parameters
switch|Switch
switchsolver|Switch Solver
switchvalue|Switch Value
targetrel|Target Relationship
terrainobject|Terrain Object
thinplatecollider|Thin Plate/Thin Plate Collider
twostateconrel|Two State Constraint Relationship
uniformforce|Uniform Force
vectorfield|Vector Field
vectorfieldvisualization|Vector Field Visualization
velimpulseforce|Velocity Impulse Force
vellumconstraintproperty|Vellum Constraint Properties
vellumconstraints|Vellum Constraints
vellumobject|Vellum Object
vellumrestblend|Vellum Rest Blend
vellumsolver|Vellum Solver
vellumsource|Vellum Source
visualizegeometry|Visualize Geometry
volume|SDF Representation
volumecollider|Volume/Volume Collider
volumeinstancesource|Volume Instance Source
volumesource|Volume Source
vopforce|VOP Force
voronoifractureconfigureobject|Voronoi Fracture Configure Object
voronoifractureparms|Voronoi Fracture Parameters
voronoifracturesolver|Voronoi Fracture Solver
vortexforce|Vortex Force
whitewaterobject|Whitewater Object
whitewatersolver|Whitewater Solver
windforce|Wind Force
wireangularconstraint|Wire Angular Constraint
wireangularspringconstraint|Wire Angular Spring Constraint
wireconfigureobject|Wire Configure Object
wireelasticity|Wire Elasticity
wireglueconstraint|Wire Glue Constraint
wireobject|Wire Object
wirephysparms|Wire Physical Parameters
wireplasticity|Wire Plasticity
wiresolver|Wire Solver
wirevisualization|Wire Visualization
wirevolumecollider|Wire/Volume Collider
wirewirecollider|Wire/Wire Collider
""",
    "obj": """\
agentcam|Agent Cam
alembicarchive|Alembic Archive
alembicxform|Alembic Xform
ambient|Ambient Light
autobonechaininterface|Auto Bone Chain Interface
blend|Blend
blendsticky|Blend Sticky
bone|Bone
cam|Camera
common_obj_parms|Common object parameters
dopnet|Dop Network
envlight|Environment Light
fetch|Fetch
formationcrowdsexample|Formation Crowd Example
fuzzyObstacleAvoidance|Fuzzy Logic Obstacle Avoidance Example
fuzzystatetransition|Fuzzy Logic State Transition Example
geo|Geometry
gltf_hierarchy|glTF
groommerge|Groom Merge
guidedeform|Guide Deform
guidegroom|Guide Groom
guidesim|Guide Simulate
haircardgen|Hair Card Generate
haircardtexexample|Hair Card Texture Example
hairgen|Hair Generate
handle|Handle
hlight|Light
indirectlight|Indirect Light
instance|Instance
labs--fire_presets|Labs Fire Presets
labs--lod_hierarchy|Labs LOD Hierarchy
labs--rendergeo-1.0|Labs Render Geometry
light|Light template
lopimport|LOP Import
lopimportcam|LOP Import Camera
mcacclaim|Mocap Acclaim
microphone|Microphone
mocapbiped1|Mocap Biped 1
mocapbiped2|Mocap Biped 2
mocapbiped3|Mocap Biped 3
null|Null
path|Path
pathcv|PathCV
pythonscript|Python Script
ragdollrunexample|Ragdoll Run Example
refimage|Reference Image
rivet|Rivet
simplebiped|Simple Biped
simplefemale|Simple Female
simplemale|Simple Male
sound|Sound
stadiumcrowdsexample|Stadium Crowds Example
stereocam|Stereo Camera Template
stereocamrig|Stereo Camera Rig
sticky|Sticky
streetcrowdsexample|Street Crowd Example
subnet|Subnet
switcher|Switcher
topnet|TOP Network
viewportisolator|Viewport Isolator
vrcam|VR Camera
""",
    "lop": """\
additionalrendervars|Additional Render Vars
addvariant|Add Variant
apexanimate|APEX Animate
apexsoprigbuilder|APEX SOP Rig Builder
assetreference|Asset Reference
assignmaterial|Assign Material
assignprototypes|Assign Prototypes
attribvop|Attribute VOP
attribwrangle|Attribute Wrangle
autoselectlod|Auto Select LOD
backgroundplate-2.0|Karma Background Plate
bakeapexscene|Bake APEX Scene
bakeskinning|Bake UsdSkel Skinning
basiscurves|Basis Curves
begincontextoptionsblock|Begin Context Options Block
blend|Blend
blendconstraint|Blend Constraint
cache|Cache
camera|Camera
capsule|Capsule
collection|Collection
componentgeometry|Component Geometry
componentgeometryvariants|Component Geometry Variants
componentmaterial|Component Material
componentoutput|Component Output
cone|Cone
configureapexrig|Configure APEX Rig
configureguidedeform|Configure Guide Deform
configurelayer|Configure Layer
configureprimitive|Configure Primitives
configureproperty|Configure Properties
configurestage|Configure Stage
coordsys|Coordinate System
copyproperty|Copy Property
copytopoints|Copy to Points
createlod|Create LOD
createxform|Xform
cube|Cube
cylinder|Cylinder
distantlight|Distant Light
domelight|Dome Light
drawmode|Draw Mode
drop|Drop
duplicate|Duplicate
edit|Edit
editcontextoptions|Edit Context Options
editmaterial|Edit Material Network
editmaterialproperties|Edit Material Properties
editproperties|Edit Properties
editpropertiesfromnode|Edit Properties From Node
editprototypes|Edit Prototypes
edittargetlayer|Edit Target Layer
error|Error
explorevariants|Explore Variants
extractinstances|Extract Instances
fetch|Fetch
filecache|File Cache
followpathconstraint|Follow Path Constraint
foreach|For Each
geoclipsequence|Geometry Clip Sequence
geometrycolor|Geometry Color
geometrylight|Geometry Light
geometrysequence|Geometry Sequence
geometrysubsetvop|Geometry Subset VOP
graftbranches|Graft Branches
graftstages|Graft Stages
hdadynamicpayload|HDA Dynamic Payload
hermitecurves|Hermite Curves
houdinicrowdprocedural|Houdini Procedural: Crowd
houdinifeatherprocedural|Houdini Procedural: Feather
houdinihairprocedural|Houdini Procedural: Hair
houdinioceanprocedural|Houdini Procedural: Ocean
houdinipreviewprocedurals|Houdini Preview Procedurals
houdinirbdprocedural|Houdini Procedural: RBD
huskimagemetadata|Husk Image Metadata
imagefilter|Image Filter
inlineusd|Inline USD
insertionpoint|Insertion Point
isolatescene|Isolate Scene
karmablockerlightfilter|Karma Blocker Light Filter
karmacryptomatte|Karma Cryptomatte
karmafogbox|Karma Fog Box
karmaphysicalsky|Karma Physical Sky
karmarenderproducts|Karma Render Products
karmarendersettings|Karma Render Settings
karmaskyatmosphere|Karma Sky Atmosphere
karmaskydomelight|Karma Sky Dome Light
karmastandardrendervars|Karma Standard Render Vars
karmatexturebaker|Karma Texture Baker
kinefx--sopcharacterimport|SOP Import UsdSkel Character
labs--biome_plant_scatter_import-1.0|Labs Biome Plant Scatter Import
labs--karma-2.0|Labs Karma
labs--karma_aovs_for_prman_denoiser-1.0|Labs Karma AOVs for RenderMan Denoiser
labs--ml_cv_directory_variant-1.0|Labs ML CV Directory Variant
labs--ml_cv_dome_camera-1.0|Labs ML CV Dome Camera
labs--ml_cv_synthetics_karma_rop-1.1|Labs ML CV Synthetics Karma Rop
labs--relight_gsplats-1.2|Labs Relight GSplats
labs--zibravdb_import-1.0|Labs ZibraVDB Import
layerbreak|Layer Break
layerreplace|Layer Replace
light|Light
lightfilterlibrary|Light Filter Library
lightlinker|Light Linker
lightmixer|Light Mixer
liverender|Live Render
loadlayer|Load Layer for Editing
loftpayloadinfo|Loft Payload Info
lookatconstraint|Look At Constraint
lpetag|LPE Tag
maskfrombounds|Mask from Bounds
matchsize|Match Size
materiallibrary|Material Library
materiallinker|Material Linker
materialvariation|Material Variation
merge|Merge
mergepointinstancers|Merge PointInstancers
mesh|Mesh
modifypaths|Modify Paths
modifypointinstances|Modify Point Instances
motionblur|Motion Blur
null|Null
output|Output
paintinstances|Paint Instances
parentconstraint|Parent Constraint
plane|Plane
pointinstancer|PointInstancer
points|Points
pointsconstraint|Points Constraint
pointxform|Transform by SOP Points
portallight|Portal Light
primitive|Primitive
prune|Prune
pythonscript|Python Script
rbddestruction|RBD Destruction
reference|Reference
relocate|Relocates
rendergeometrysettings|Render Geometry Settings
renderpass|Render Pass
renderproduct|Render Product
rendersettings|Render Settings
rendervar|Render Var
resampletransforms|Resample Transforms
restructurescenegraph|Restructure Scene Graph
retimeinstances|Retime Instances
scatterinstances|Scatter Instances
scenedoctor|Scene Doctor
sceneimport|Scene Import
scope|Scope
setextents|Set Extents
setvariant|Set Variant
shadowcatcher|Karma Shadow Catcher
shotlayeredit|Shot Layer Edit
shotload|Shot Load
shotoutput|Shot Output
shotsplit|Shot Split
shotswitch|Shot Switch
simulationproxy|Simulation Proxy
sopcreate|SOP Create
sopcrowdimport|SOP Import Crowd
sopimport|SOP Import
sopimportapexscene|SOP Import APEX Scene
sopmodify|SOP Modify
sphere|Sphere
splitpointinstancers|Split PointInstancers
splitprimitive|Split Primitive
splitscene|Split Scene
stagemanager|Stage Manager
storeparametervalues|Store Parameter Values
sublayer|Sublayer
subnet|Subnet
surfaceconstraint|Surface Constraint
switch|Switch
texturemateriallibrary|Texture Material Library
timeshift|TimeShift
transformuv|Transform UV
unassignmaterial|Unassign Material
usd_rop|USD ROP
usdrender_rop|USD Render ROP
valueclip|Value Clip
varymaterialassignment|Vary Material Assignment
volume|Volume
xform|Transform
""",
    "vop": """\
DelayedReadArchive|Delayed Read Archive
_lensshader_common|_lensshader_common
aaflownoise|Anti-Aliased Flow Noise
aanoise|Anti-Aliased Noise
aarampparm|Anti-Aliased Ramp Parameter
abs|Absolute
add|Add
addattrib|Add Attribute
addconst|Add Constant
addgroup|Add Point to Group
addpoint|Add Point
addprim|Add Primitive
addsteerforce|Add Steer Force
addvertex|Add Vertex
addwindforce|Add Wind Force
advectbyvolumes|Advect by Volumes
agentclipcatalog|Agent Clip Catalog
agentcliplength|Agent Clip Length
agentclipnames|Agent Clip Names
agentclipsample|Agent Clip Sample
agentclipsamplerate|Agent Clip Sample Rate
agentcliptimes|Agent Clip Times
agentclipweights|Agent Clip Weights
agentconverttransforms|Agent Convert Transforms
agentlayerbindings|Agent Layer Bindings
agentlayername|Agent Layer Name
agentlayers|Agent Layers
agentlayershapes|Agent Layer Shapes
agentrigchildren|Agent Rig Children
agentrigfind|Agent Rig Find
agentrigparent|Agent Rig Parent
agenttransformcount|Agent Transform Count
agenttransformnames|Agent Transform Names
agenttransforms|Agent Transforms
albedo|Get BSDF Albedo
align|Align
alphamix|Alpha Mix
ambient|Ambient
and|And
append|Append
argsort|argsort
arraylength|Array Length
atan|Arctangent
atten|Attenuated Falloff
avg|Average
avgcomp|Average Vector Component
bakeexports|Bake Exports
bbox|Bounding Box
bias|Bias
bind|Bind
blendregions|Blend Regions
block_begin|Block Begin
block_begin_for|Block Begin For
block_begin_foreach|Block Begin For-Each
block_begin_if|Block Begin If
block_end|Block End
block_end_breakif|Block End Break-If
block_end_while|Block End While
boxclip|Box Clip
boxes|Boxes
boxtile|Tiled Boxes
bricker|Bricker
brushedcircles|Brushed Circles
brushedmetalshader|Brushed Metal Shader
bsdftint|BSDF Tint
bumpnoise|Bump Noise
bumptonormalmap|Bump To Normal Map
burlap|Burlap
burlap_pattern|Burlap Pattern
carpaintshader|Car Paint Shader
cavities|Cavities
ceiling|Ceiling
cellcracks|Cellular Cracks
cellnoise|Cellular Noise
ch|Get a Channel or Parameter Value
chattr|Get CHOP Attribute
checkered|Checkered
chinput|Get Channel Value
chinputn|Get Channel Value by Name
chop|Get a CHOP Channel Value
chr|Character to String
chsetattr|Set CHOP Attribute
clamp|Clamp
classcast|Class Cast
classicshader|Classic Shader
classicshadercore|Classic Shader Core
cloudnoise|Cloud Noise
collect|Collect
colorcorrection|Color Correction
colormap|Color Map
colormix|Color Mix
compare|Compare
complement|Complement
composite|Composite
computelighting|Compute Lighting
computenormal|Compute Normal
computetan|Compute Tangents
conductorfresnel|Conductor Fresnel
conserveenergy|Conserve Energy
constant|Constant
contains|Array Contains
contour|Contour
copy|Copy
cosine|Cosine
crackle|Crackle
cross|Cross Product
ctransform|Color Transform
curlnoise|Curl Noise
curlnoise2d|Curl Noise 2D
curvature|Curvature
cvexbuilder|CVEX Shader Builder
decal_a|Decal
degtorad|Degrees to Radians
densitytoopacity|Volume Density to Opacity
depthmap|Depth Map
determinant|Determinant
dictkeys|Dictionary Keys
dictlen|Dictionary Length
dimport|Import Displacement Variable
directlighting|Direct Lighting
dirtmask|Dirt Mask
displace|Displace
displacenml|Displace Along Normal
displacetexture|Displacement Texture
distance|Distance
divconst|Divide Constant
divide|Divide
dot|Dot Product
dualrest|Dual Rest
dualrestsolver|Dual Rest Solver
edgefalloff|Edge Falloff
efit|Fit Range (Unclamped)
egg_shell|Eggshell Pattern
eigenvalues|Eigenvalues
endswith|Ends With
enginecurvegen|Houdini Engine Procedural: Curve Generate
engineinstance|Instance with Hscript Procedural
enginepointgen|Houdini Engine Procedural: Point Generate
envmap|Environment Map
eulertoquat|Euler to Quaternion
exp|Exponential
extractxform|Extract Transform
fakecaustics|Fake Caustics
fastshadow|Fast Shadow
fibratus|Fibratus
fieldname|Field Name
fieldparm|Field Parameter
filamentsample|Filament Sample
file|Delayed Load Procedural
filtershadow|Filter Shadow
filterstep|Filter Step
filterwidth|Filter Width
find|Array Find Indices
findattribval|Find Attribute Value
findattribvalcount|Find Attribute Value Count
findattribvalindex|Find Attribute Value by Index
findsingle|Array Find Index
fit|Fit Range
floattohmatx|Float to Matrix
floattohvec|Float to Vector4
floattoint|Float to Integer
floattomatx|Float to Matrix3
floattomatx2|Float to Matrix2
floattovec|Float to Vector
floattovec2|Float to Vector2
floccus|Floccus
floor|Floor
flownoise|Flow Noise
forpoints|Point Loop
frac|Fraction
fractus|Fractus
fresnel|Fresnel
fromndc|From NDC
fromndcgeo|From NDC
frompolar|From Polar
frontface|Front Face
fur|Fur Procedural
furguideglobal|Fur Guide Global Variables
furguideoutput|Fur Guide Output Variables and Parameters
furrows|Furrows
furskinglobal|Fur Skin Global Variables
furskinoutput|Fur Skin Output Variables and Parameters
fuzzyand|Fuzzy And
fuzzydefuzz|Fuzzy Defuzz
fuzzyinference|Fuzzy Inference
fuzzyinferencemirror|Fuzzy Inference Mirror
fuzzyinput|Fuzzy Input
fuzzynot|Fuzzy Not
fuzzyor|Fuzzy Or
fuzzysenseobs|Fuzzy Obstacle Sense
gain|Gain
gather|RSL Gather Loop
generalfresnel|General Fresnel
genericshader|Generic Shader
geometryvopglobal|Geometry VOP Global Parameters
geometryvopoutput|Geometry VOP Output Variables
getattrib|Get Attribute
getblurP|Get Blur P
getdictelement|Get Dictionary Element
getelement|Get Element
getlayerexport|Get Layer Export
getobjxform|Get Object Transform
getprimid|Get Primitive ID
getptextureid|Get PTexture ID
gettransformchannels|Get Channel Transform
gingham|Gingham Checks
global|Global Variables
gradient3d|Gradient 3D
grandom|Gaussian Random
grandomuv|Gaussian Random UV
hairnormal|Hair Normal
hairshader|Hair Shader
hasinput|Has Input
haskey|Has Key
hasmetadata|Metadata
hextile|Tiled Hexagons
hilownoise|High-Low Noise
hmatxgetcompon|Get Matrix Component
hmatxsetcompon|Set Matrix Component
hmatxtofloat|Matrix to Float
hmatxtohvec|Matrix to Vector4
hmtlxbias|MtlX Bias
hmtlxcircles2d|MtlX Circles 2D
hmtlxcomplement|Mtlx Complement
hmtlxcomplementcolor|Mtlx Complement Color
hmtlxcubicrampc|MtlX Color Cubic Ramp
hmtlxcubicrampf|MtlX Float Cubic Ramp
hmtlxfacingratio|MtlX Facing Ratio
hmtlxgain|MtlX Gain
hmtlxhcatmullrom|MtlX Hcatmullrom
hmtlxhinvlinear|MtlX Hinvlinear
hmtlxhuniformcubic|MtlX Huniformcubic
hmtlxhuniformramp|MtlX Huniformramp
hmtlxpbrtextureset|MtlX PBR Texture Set
hmtlxrampc|MtlX Color Ramp
hmtlxrampf|MtlX Float Ramp
hmtlxudimoffset|MtlX UDIM Offset
hmtlxudimpatch|MtlX UDIM Patch
hsvtorgb|HSV to RGB
hueshift|Hue Shift
hvecgetcompon|Get Vector4 Component
hvecsetcompon|Set Vector4 Component
hvectofloat|Vector4 to Float
hvectohmatx|Vector4 to Matrix
hvectovec|Vector4 to Vector
hvectovec2|Vector4 to Vector2
ifconnected|If Connected
illuminance|Illuminance Loop
image3d|Image 3D Iso-Texture Procedural
image3dvolume|Image 3D Volume Procedural
importance_remap|Importance Remap
importattrib|Import Attribute
importdetail|Import Detail Attribute
importpoint|Import Point Attribute
importprim|Import Primitive Attribute
importvertex|Import Vertex Attribute
indirectlighting|Indirect Lighting
ingroup|Point In Group
inline|Inline Code
inprimorptgroup|In Group
insert|Insert
intersect|Intersect
intersectall|Intersect All
inttofloat|Integer to Float
inttovec|Integer to Vector
invert|Invert
irradiance|Irradiance
isalpha|Is Alphabetic
isconnected|Is Connected
isdigit|Is Digit
isfinite|Is Finite
isfog|Is Fog Ray
isfrontface|Is Front Face
isnan|Is NAN
isshadow|Is Shadow Ray
jitteredhairnormal|Jittered Hair Normal
join|Join Strings
kinefx--addjoint|Add Joint
kinefx--bindpointtransform|Bind Point Transform
kinefx--blendtransforms|Blend Transforms
kinefx--collidegeometry|Collide Geometry
kinefx--combinelocaltransform|Combine Local Transform
kinefx--dirtochild|Direction to Child
kinefx--dirtoparent|Direction to Parent
kinefx--extractlocaltransform|Extract Local Transform
kinefx--filterpointxforms|Filter Point Transforms
kinefx--findpointxform|Find Point Transform
kinefx--foreachtransform|For Each Transform
kinefx--getdescendantxforms|Get Descendant Transforms
kinefx--getfbikattribs|Get FBIK Attributes
kinefx--getfullbodycom|Get Full Body COM
kinefx--getjointchainaxes|Get Joint Chain Axes
kinefx--getparenttransform|Get Parent Transform
kinefx--getpointparent|Get Parent
kinefx--getpointtransform|Get Point Transform
kinefx--getpointtransforms|Get Point Transforms
kinefx--jointangle|Joint Angle
kinefx--lookat|Look At (KinefX)
kinefx--lookatconstraint|Look At Constraint
kinefx--mappoint|Map Point
kinefx--offsettransform|Offset Transform
kinefx--parentblend|Parent Blend
kinefx--parentconstraint|Parent Constraint
kinefx--posedifference|Pose Difference
kinefx--realisticshoulder|Realistic Shoulder
kinefx--resolvemapping|Resolve Mapping Attribute
kinefx--reversefoot|Reverse Foot
kinefx--setpointtransform|Set Point Transform
kinefx--setpointtransforms|Set Point Transforms
kinefx--solvecurve|Curve Solver
kinefx--solveik|IK Solver
kinefx--stashtransform|Stash Transform
kinefx--transformfrompath|Transform From Path
kinefx--transformfromsurface|Transform From Surface
kinefx--twoboneik|Two Bone IK
kma_ao|Karma Ambient Occlusion
kma_aov-2.0|Karma AOV 2.0
kma_camerafalloff|Karma Camera Falloff
kma_curvature|Karma Curvature
kma_deriv2d|Karma 2D Derivatives
kma_distance|Karma Distance
kma_fur|Karma Fur
kma_hair|Karma Hair
kma_hextiled_texture|Karma Hexagonal Tiling Texture
kma_hextiled_triplanar|Karma Hexagonal Tiling Triplanar
kma_lfilter_attenuation|Karma Light Filter Attenuation
kma_lfilter_barndoor|Karma Light Filter Barndoor
kma_lfilter_gel|Karma Light Filter Gel
kma_lfilter_gobo|Karma Light Filter Gobo
kma_light_projection|Karma Light Projection
kma_material_properties|Karma Material Properties
kma_melanin|Karma Melanin
kma_ocio_transform|Karma OCIO Color Transform
kma_pcread|Karma Point Cloud Read
kma_physicallens|Karma Physical Lens
kma_physicallenscore|Karma Physical Lens Core
kma_pyrofirecolor|Karma Pyro Fire Color
kma_pyrofireemission|Karma Pyro Fire Emission
kma_pyropreview|XPU Pyro Preview
kma_pyroscattercolor|Karma Pyro Scatter Color
kma_pyroscatteremission|Karma Pyro Scatter Emission
kma_pyroshader|Karma Pyro Shader
kma_pyrosmokecolor|Karma Pyro Smoke Color
kma_pyrovolumemask|Karma Pyro Volume Mask
kma_rampconst|Karma Ramp Constant
kma_rayhitlevelfalloff|Karma Ray Hit Level Falloff
kma_rayimport-2.0|Karma Ray Import
kma_rayswitch|Karma Ray Switch
kma_roomlens|Karma Room Lens
kma_roommap|Karma Room Map
kma_roundededge-|USD Transform 2D
kma_stderiv-|USD Prim Var Reader
kma_tangentrotate|Karma Tangent Rotate
kma_uvlens|Karma UV Lens
kma_volume|Karma Volume
kma_voronoinoise2d|Karma Voronoi Noise 2D
kma_voronoinoise3d|Karma Voronoi Noise 3D
kma_whitewater|Karma Whitewater
lambert|Lambert
layercomp|Layer Composite
layermix|Layer Mix
layerpack|Layer Pack
layerunpack|Layer Unpack
len|Length
length|Length
lens_bokeh|Lens Bokeh
lens_chromaticaberration|Lens Chromatic Aberration
lens_coordinates|Lens Coordinates
lens_distort|Lens Distort
lens_opencv_distort|Lens OpenCV Distort
lens_parameters|Lens Parameters
lens_rollingshutter|Lens Rolling Shutter
lens_shuttercurve|Lens Shutter Curve
lighting|Lighting Model
limits|Limits
limport|Import Light Variable
logarithm|Logarithm
lookat|Look At
luminance|Luminance
m2tom3|Matrix2 to Matrix3
m2tom4|Matrix2 to Matrix4
m3tom2|Matrix3 to Matrix2
m3tom4|Matrix3 to Matrix4
m4tom2|Matrix4 to Matrix2
m4tom3|Matrix4 to Matrix3
maddconst|Multiply Add Constant
makeinstancexform|Make Instance Transform
makexform|Make Transform
mandel|Mandelbrot Set
matcapshader|MatCap Shader
materialbuilder|Material shader builder
matte|Matte
matx2getcompon|Get Matrix2 Component
matx2setcompon|Set Matrix2 Component
matx2tofloat|Matrix2 to Float
matx2tovec2|Matrix2 to Vector2
matxgetcompon|Get Matrix3 Component
matxsetcompon|Set Matrix3 Component
matxtofloat|Matrix3 to Float
matxtoquat|Matrix3 to Quaternion
matxtovec|Matrix3 to Vector
max|Maximum
maxcomp|Max Vector Component
metaattrib|Metaball Attribute
metadata|Metadata
metadensity|Metaball Density
metaimport|Meta-Loop Import
metanext|Meta-Loop Next
metaspace|Metaball Space
metastart|Meta-Loop Start
metaweight|Metaball Weight
method|Method
methodcall|Method Call
methodinput|Method Input
methodsubnet|Method Subnet
min|Minimum
mincomp|Min Vector Component
minpos|Minimum Position
mix|Mix
modulo|Modulo
mtlxUsdPreviewSurface|MtlX USD Preview Surface
mtlxUsdPrimvarReader|MtlX USD Primvar Reader
mtlxUsdTransform2d|MtlX USD Transform 2D
mtlxUsdUVTexture|MtlX USD UV Texture
mtlxUsdUVTexture23|MtlX USD UV Texture
mtlxabsorption_vdf|MtlX Absorption Vdf
mtlxabsval|MtlX Absval
mtlxacescg_to_lin_rec709|MtlX Acescg To Lin Rec709
mtlxacos|MtlX Acos
mtlxadd|MtlX Add
mtlxadobergb_to_lin_rec709|MtlX Adobergb To Lin Rec709
mtlxand|MtlX And
mtlxanisotropic_vdf|MtlX Anisotropic Vdf
mtlxartistic_ior|MtlX Artistic Ior
mtlxasin|MtlX Asin
mtlxatan2|MtlX Atan2
mtlxbitangent|MtlX Bitangent
mtlxblackbody|MtlX Blackbody
mtlxblur|MtlX Blur
mtlxbump|MtlX Bump
mtlxburley_diffuse_bsdf|MtlX Burley Diffuse Bsdf
mtlxburn|MtlX Burn
mtlxceil|MtlX Ceil
mtlxcellnoise2d|MtlX Cellnoise2D
mtlxcellnoise3d|MtlX Cellnoise3D
mtlxcheckerboard|MtlX Checkerboard
mtlxchiang_hair_absorption_from_color|MtlX Chiang Hair Absorption from Color
mtlxchiang_hair_bsdf|MtlX Chiang Hair BSDF
mtlxchiang_hair_roughness|MtlX Chiang Hair Roughness
mtlxcircle|MtlX Circle
mtlxclamp|MtlX Clamp
mtlxcloverleaf|MtlX Cloverleaf
mtlxcolorcorrect|MtlX Color Correct
mtlxcombine2|MtlX Combine2
mtlxcombine3|MtlX Combine3
mtlxcombine4|MtlX Combine4
mtlxconductor_bsdf|MtlX Conductor Bsdf
mtlxconical_edf|MtlX Conical Edf
mtlxconstant|MtlX Constant
mtlxcontrast|MtlX Contrast
mtlxconvert|MtlX Convert
mtlxcos|MtlX Cos
mtlxcreatematrix|MtlX Create Matrix
mtlxcreatematrix3|MtlX Create Matrix (3×3)
mtlxcrosshatch|MtlX Crosshatch
mtlxcrossproduct|MtlX Crossproduct
mtlxdeon_hair_absorption_from_melanin|MtlX Deon Hair Absorption from Melanin
mtlxdeterminant|MtlX Determinant
mtlxdielectric_bsdf|MtlX Dielectric Bsdf
mtlxdifference|MtlX Difference
mtlxdirectional_light|MtlX Directional Light
mtlxdisjointover|MtlX Disjointover
mtlxdisney_principled|MtlX Disney Principled
mtlxdisplacement|MtlX Displacement
mtlxdistance|MtlX Distance
mtlxdivide|MtlX Divide
mtlxdodge|MtlX Dodge
mtlxdot|MtlX Dot
mtlxdotproduct|MtlX Dotproduct
mtlxexp|MtlX Exp
mtlxextract|MtlX Extract
mtlxfacingratio|MtlX Facing Ratio
mtlxflake2d|MtlX Flake 2D
mtlxflake3d|MtlX Flake 3D
mtlxfloor|MtlX Floor
mtlxfract|MtlX Fract
mtlxfractal2d|MtlX Fractal2D
mtlxfractal3d|MtlX Fractal3D
mtlxframe|MtlX Frame
mtlxg18_rec709_to_lin_rec709|MtlX G18 Rec709 To Lin Rec709
mtlxg22_ap1_to_lin_rec709|MtlX G22 Ap1 To Lin Rec709
mtlxg22_rec709_to_lin_rec709|MtlX G22 Rec709 To Lin Rec709
mtlxgeneralized_schlick_bsdf|MtlX Generalized Schlick Bsdf
mtlxgeneralized_schlick_edf|MtlX Generalized Schlick Edf
mtlxgeomcolor|MtlX Geometry Color
mtlxgeompropvalue|MtlX Geometry Property Value
mtlxgeompropvalueuniform|MtlX Geometry Property Value Uniform
mtlxglossiness_anisotropy|MtlX Glossiness Anisotropy
mtlxgltf_anisotropy_image|MtlX Khronos glTF Anisotropy Image Utility
mtlxgltf_colorimage|MtlX Gltf Colorimage
mtlxgltf_image|MtlX Gltf Image
mtlxgltf_imagev|MtlX gltf image (vector)
mtlxgltf_iridescence_thickness|MtlX Gltf Iridescence Thickness
mtlxgltf_material|mtlxgltf_material
mtlxgltf_normalmap|MtlX Gltf Normalmap
mtlxgltf_pbr|MtlX glTF Pbr
mtlxgooch_shade|MtlX Gooch Shade
mtlxgrid|MtlX Grid
mtlxheighttonormal|MtlX Heighttonormal
mtlxhexagon|MtlX Hexagon
mtlxhextiledimage|MtlX Hex Tiled Image
mtlxhextilednormalmap|MtlX Hex Tiled Normal Map
mtlxhsvadjust|MtlX Hsvadjust
mtlxhsvtorgb|MtlX HSV to RGB
mtlxifequal|MtlX If Equal
mtlxifequalbool|MtlX If Equal (Boolean)
mtlxifgreater|MtlX If Greater
mtlxifgreaterbool|MtlX If Greater (Boolean)
mtlxifgreatereq|MtlX If Greater or Equal
mtlxifgreatereqbool|MtlX If Greater or Equal (Boolean)
mtlximage|MtlX Image
mtlxin|MtlX In
mtlxinside|MtlX Inside
mtlxinvert|MtlX Invert
mtlxinvertmatrix|MtlX Invertmatrix
mtlxlatlongimage|MtlX Lat Long Image
mtlxlayer|MtlX Layer
mtlxlight|MtlX Light
mtlxlin_adobergb_to_lin_rec709|MtlX Lin Adobergb To Lin Rec709
mtlxlin_displayp3_to_lin_rec709|MtlX Lin Displayp3 To Lin Rec709
mtlxline|MtlX Line
mtlxln|MtlX Ln
mtlxluminance|MtlX Luminance
mtlxmagnitude|MtlX Magnitude
mtlxmask|MtlX Mask
mtlxmatte|MtlX Matte
mtlxmax|MtlX Max
mtlxmeasured_edf|MtlX Measured Edf
mtlxmin|MtlX Min
mtlxminus|MtlX Minus
mtlxmix|MtlX Mix
mtlxmodulo|MtlX Modulo
mtlxmultiply|MtlX Multiply
mtlxnoise2d|MtlX Noise2D
mtlxnoise3d|MtlX Noise3D
mtlxnormal|MtlX Normal
mtlxnormalize|MtlX Normalize
mtlxnormalmap|MtlX Normalmap
mtlxnot|MtlX Not
mtlxopen_pbr_anisotropy|MtlX Open PBR Anisotropy
mtlxopen_pbr_surface|MtlX OpenPBR Surface
mtlxopen_pbr_surface_to_standard_surface|mtlxopen_pbr_surface_to_standard_surface
mtlxor|MtlX Xor
mtlxoren_nayar_diffuse_bsdf|MtlX Oren Nayar Diffuse Bsdf
mtlxout|MtlX Out
mtlxoutside|MtlX Outside
mtlxover|MtlX Over
mtlxoverlay|MtlX Overlay
mtlxplace2d|MtlX Place2D
mtlxplus|MtlX Plus
mtlxpoint_light|MtlX Point Light
mtlxposition|MtlX Position
mtlxpower|MtlX Power
mtlxpremult|MtlX Premult
mtlxramp|MtlX Ramp
mtlxramp4|MtlX Ramp4
mtlxramp_gradient|MtlX Ramp Gradiant
mtlxramplr|MtlX Ramplr
mtlxramptb|MtlX Ramptb
mtlxrandomcolor|MtlX Random Color
mtlxrandomfloat|MtlX Random Float
mtlxrange|MtlX Range
mtlxrec709_display_to_lin_rec709|MtlX Rec709 Display To Lin Rec709
mtlxreflect|MtlX Reflect
mtlxrefract|MtlX Refract
mtlxremap|MtlX Remap
mtlxrgbtohsv|MtlX RGB to HSV
mtlxrotate2d|MtlX Rotate2D
mtlxrotate3d|MtlX Rotate3D
mtlxroughness_anisotropy|MtlX Roughness Anisotropy
mtlxroughness_dual|MtlX Roughness Dual
mtlxround|MtlX Round
mtlxsafepower|MtlX Safe Power
mtlxsaturate|MtlX Saturate
mtlxscreen|MtlX Screen
mtlxseparate2|MtlX Separate2
mtlxseparate3c|MtlX Separate Color 3
mtlxseparate3v|MtlX Separate Vector 3
mtlxseparate4c|MtlX Separate Color 4
mtlxseparate4v|MtlX Separate Vector 4
mtlxsheen_bsdf|MtlX Sheen Bsdf
mtlxsign|MtlX Sign
mtlxsin|MtlX Sin
mtlxsmoothstep|MtlX Smoothstep
mtlxsplitlr|MtlX Splitlr
mtlxsplittb|MtlX Splittb
mtlxspot_light|MtlX Spot Light
mtlxsqrt|MtlX Sqrt
mtlxsrgb_displayp3_to_lin_rec709|MtlX Srgb Displayp3 To Lin Rec709
mtlxsrgb_texture_to_lin_rec709|MtlX Srgb Texture To Lin Rec709
mtlxstandard_surface|MtlX Standard Surface
mtlxstandard_surface_to_UsdPreviewSurface|MtlX Standard Surface to USD Preview Surface
mtlxstandard_surface_to_gltf_pbr|MtlX Standard Surface To Gltf Pbr
mtlxstandard_surface_to_open_pbr_surface|mtlxstandard_surface_to_open_pbr_surface
mtlxsubsurface_bsdf|MtlX Subsurface BSDF
mtlxsubtract|MtlX Subtract
mtlxsurface|MtlX Surface
mtlxsurface_unlit|MtlX Surface Unlit
mtlxsurfacematerial|MtlX Surface Material
mtlxswitch|MtlX Switch
mtlxtan|MtlX Tan
mtlxtangent|MtlX Tangent
mtlxtexcoord|MtlX Texcoord
mtlxtiledcircles|MtlX Tiled Circles
mtlxtiledcloverleafs|MtlX Tiled Cloverleafs
mtlxtiledhexagons|MtlX Tiled Hexagons
mtlxtiledimage|MtlX Tiled Image
mtlxtime|MtlX Time
mtlxtransformmatrix|MtlX Transform Matrix
mtlxtransformnormal|MtlX Transform Normal
mtlxtransformpoint|MtlX Transform Point
mtlxtransformvector|MtlX Transform Vector
mtlxtranslucent_bsdf|MtlX Translucent Bsdf
mtlxtranspose|MtlX Transpose
mtlxtrianglewave|MtlX Triangle Wave
mtlxtriplanarprojection|MtlX Triplanar Projection
mtlxunifiednoise2d|MtlX Unified Noise 2D
mtlxunifiednoise3d|MtlX Unified Noise 3D
mtlxuniform_edf|MtlX Uniform Edf
mtlxunpremult|MtlX Unpremult
mtlxviewdirection|MtlX View Direction
mtlxvolume|MtlX Volume
mtlxvolumematerial|MtlX Volume Material
mtlxworleynoise2d|MtlX Worley Noise 2D
mtlxworleynoise3d|MtlX Worley Noise 3D
mtlxxor|MtlX Xxor
mulconst|Multiply Constant
multiply|Multiply
nearpoint|Near Point
negate|Negate
neighbourcountfile|Neighbor Count File
neighbourfile|Neighbor File
neighbours|Neighbors
newgroup|Create Point Group
normalclamp|Normal Clamp
normalfalloff|Normal Falloff
normalize|Normalize
not|Not
npoints|Point Count
nrandom|Non-Deterministic Random
null|Null
nuniqueval|Unique Value Count of Attribute
occlusion|Occlusion
oceansamplelayers|Ocean Sample Layers
ocio_import|Import Properties from OpenColorIO
ocio_transform|OCIO Color Transform
ocio_transformview|OCIO Color Transform View
optransform|Get an Object Transform
or|Or
oren|Oren-Nayar
orient|Orient
oscill|Oscillations
osd_facecount|OpenSubdiv Face Count
osd_firstpatch|OpenSubdiv First Patch
osd_limit|OpenSubdiv Limit
osd_limitcurvature|OpenSubdiv Limit Curvature
osd_limitgradient|OpenSubdiv Limit Gradient
osd_limitnormal|OpenSubdiv Limit Normal
osd_limitsurface|OpenSubdiv Limit Surface
osd_limitvertex|OpenSubdiv Limit
osd_lookupface|OpenSubdiv Lookup Face
osd_lookuppatch|OpenSubdiv Lookup Patch
osd_patchcount|OpenSubdiv Patch Count
osl_bias|OSL Bias
osl_calculatenormal|OSL Calculate Normal
osl_dxdydz|OSL Dx/Dy/Dz
osl_environment|OSL Environment Map
osl_gain|OSL Gain
osl_log|OSL Logarithm
osl_step|OSL Step
osl_texture|OSL Texture Map
osl_transform|OSL Transform
osl_transformc|OSL Transform Color
oslbuilder|OSL Generic Shader Builder
outerproduct|Outer Product
output|Output Variables and Parameters
parameter|Parameter
pbrdiffuse|Physically Based Diffuse
pbremission|PBR Emission
pbrhair_r|PBR Hair Primary Reflection
pbrhair_trt|PBR Hair Secondary Reflection
pbrhair_tt|PBR Hair Transmission
pbrlighting|PBR Lighting
pbrmetallic|PBR Metallic Reflection
pbrnonmetallic|PBR Non-Metallic
pbrphase|PBR Volume Phase Function
pbrsingles|PBR Single Scatter
pbrsss|PBR SSS
pcclose|Point Cloud Close
pcexport|Point Cloud Export
pcfarthest|Point Cloud Farthest
pcfilter|Point Cloud Filter
pcfind|Point Cloud Find
pcfind_radius|Point Cloud Find Radius
pcimport|Point Cloud Import
pcimportbyidx|Point Cloud Import by Index
pciterate|Point Cloud Iterate
pcnumfound|Point Cloud Num Found
pcopen|Point Cloud Open
pcunshaded|Point Cloud Unshaded
pcwrite|Point Cloud Write
periodicnoise|Periodic Noise
photon_output|Photon Output Variables
physicalsss|Physical SSS
pixelarea|Pixel Area
pixelderiv|Pixel Derivative
planeclip|Plane Clip
planecount|Plane Count
planeexists|Plane Exists
planeindex|Plane Index
planename|Plane Name
planesize|Plane Size
pointbbox|Point Bounding Box
pop|Pop
pow|Power
primintrinsic|Primitive Intrinsic
primnormal|Primitive Normal
primuv|Primitive Attribute
principledshader|Principled Shader
principledshadercore|Principled Shader
print|Print
program|Run External Program Procedural
promotelayerexport|Promote Layer Exports
properties|Properties
ptinstance|Point Instance Procedural
ptlinedistance|Distance Point to Line
ptreplicate|Point Replicate
pulsetrain|Filter Pulse Train
pworleynoise|Periodic Worley Noise
pyroBlackbody|Pyro Blackbody
pyroColorCorrect|Pyro Color Correct
pyroColorModel|Pyro Color Model
pyroColorVolume|Pyro Color Volume
pyroDensityVolume|Pyro Density Volume
pyroDisplace|Pyro Displace
pyroField|Pyro Field
pyroNoise|Pyro Noise
pyroadvancedshader|Pyro Shader
pyroshader|Pyro Shader - Classic
pyroshadercore|Pyro Shader Core
qconjugate|Quaternion Conjugate
qdistance|Quaternion Distance
qexp|Quaternion Exponential
qinvert|Quaternion Invert
qlog|Quaternion Logarithm
qmultiply|Quaternion Multiply
qpow|Quaternion Power
qrotate|Rotate by Quaternion
quaternion|Quaternion
quattoeuler|Quaternion to Euler
quattomatx|Quaternion to Matrix3
quattovec|Quaternion to Angle/Axis
radtodeg|Radians to Degrees
rainbow|Rainbow
rampfilter|Ramp Filter
rampparm|Ramp Parameter
ramps|Ramps
random|Random
random_brj|Random Binary Random Jitter
random_sobol|Random Sobol
raybounce|Ray Bounce Level
rayhit|Ray Hit
rayimport|Import Ray Variable
raytrace|Ray Trace
rayweight|Ray Bounce Weight
reflect|Reflect
reflectlight|Reflected Light
refract|Refract
refractlight|Refracted Light
regex_find|Regex Find
regex_findall|Regex Findall
regex_match|Regex Match
regex_replace|Regex Replace
regex_split|Regex Split
relbbox|Relative to Bounding Box
relpointbbox|Relative to Point Bounding Box
removepoint|Remove Point
removeprim|Remove Primitive
removevalue|Remove Value
renderstate|Render State
reorder|Reorder
reporterror|Report Error
res|Resolution
reshapevalue|Reshape Value
restpos|Rest Position
reverse|Reverse
rgbtohsv|RGB to HSV
rhexes|Rounded Hexes
rings|Rings
rint|Round to Integer
ripples|Ripples
rotate|Rotate
roundededge|roundededge
rsl_bias|RenderMan Bias
rsl_calculatenormal|RenderMan Calculate Normal
rsl_ctransform|RenderMan Transform Color
rsl_depth|RenderMan Z-Depth From Camera
rsl_deriv|RenderMan Deriv
rsl_dudv|RenderMan Du/Dv
rsl_environment|RenderMan Environment Map
rsl_gain|RenderMan Gain
rsl_illuminance|RenderMan Illuminance Loop
rsl_illuminate|RenderMan Illuminate Construct
rsl_import|RenderMan Import Value
rsl_indirectdiffuse|RenderMan Indirect Diffuse
rsl_log|RenderMan Logarithm
rsl_occlusion|RenderMan Occlusion
rsl_random|Random Value
rsl_rayinfo|RenderMan Ray Information
rsl_renderstate|RenderMan Render State Information
rsl_shadow|RenderMan Shadow Map
rsl_step|RenderMan Step
rsl_surfacecolor|RenderMan Surface Color
rsl_texture|RenderMan Texture Map
rsl_textureinfo|RenderMan Texture Map Information
rsl_transform|RenderMan Transform
rstars|Rounded Stars
samplesphere|Sample Sphere
scale|Scale
scales|Scales
setagentclipnames|Set Agent Clip Names
setagentcliptimes|Set Agent Clip Times
setagentclipweights|Set Agent Clip Weights
setagentlayer|Set Agent Layer
setagenttransforms|Set Agent Transforms
setattrib|Set Attribute
setchannels|Set Channel Value
setdictelement|Set Dictionary Element
setelement|Set Element
setlayercomponent|Set Layer Component
setlayerexport|Set Layer Export
setprimvertex|Set Primitive Vertex
settransformchannels|Set Channel Tranform
shadercallexport|Shader Output Export Variables
shaderglobal|Shader Output Global Variables
shadingarea|Shading Area
shadingderiv|Shading Derivative
shadinglayer|Shading Layer Parameter
shadingnormal|Shading Normal
shadow|Shadow
shadowmap|Shadow Map
shadowmatte|Shadow Matte
sheen|Specular Sheen
sign|Sign
simport|Import Surface Variable
sine|Sine
skinshadercore|Skin Shader Core
skybox|Sky Box
slerp|Spherical Linear Interp
slice|Slice
smooth|Smooth
smoothrotation|Smooth Rotation
snippet|Snippet
softclip|Soft Clip
softdots|Soft Dots
sort|Sort
specular|Specular
splatter|Splatter
spline|Spline
split|Split String
sprite|Sprites Procedural
sqrt|Square Root
ssscomponent|SSS Component
startswith|Starts With
strip|Strip
stripes|Stripes
strlen|String Length
struct|Struct
structpack|Struct Pack
structunpack|Struct Unpack
subconst|Subtract Constant
subinput|Subnet Input
subnet|Sub Network
subnetconnector|Subnet Connector
subnetreturn|Return
suboutput|Subnet Output
subtract|Subtract
surfacecolor|Surface Color
surfacedist|Surface Distance
switch|Switch
switchlightingbsdf|Switch Lighting BSDF
swizzlehvec|Swizzle Vector4
swizzlevec|Swizzle Vector
swizzlevec2|Swizzle Vector2
tangent|Tangent
tangentnormal|Tangent Normal
tangentnormalremap|Tangent Normal Remap
tangentnormals|Tangent Normals
tet_adjacent|Tetrahedron Adjacent
tet_faceindex|Tetrahedron Adjacent
texture|Texture
texture3d|Texture 3D
texture3dbox|Texture 3D Box
texturemap|Texture Map
thinfilmfresnel|Thin Film Fresnel
timing|Timing
titlecase|Title Case
tolower|To Lower
tondc|To NDC
tondcgeo|To NDC
topolar|To Polar
toupper|To Upper
trace|Trace
transform|Transform
transformspace|Make Space Transform
translate|Translate
transpose|Transpose
trig|Trigonometric Functions
turbnoise|Turbulent Noise
twosided|Two Sided
twoway|Two Way Switch
undulatus|Undulatus
unifiednoise|Unified Noise
unifiednoise_static|Unified Noise Static
uniqueval|Unique Values of Attribute
usdglobal|USD Global Variables
usdpreviewsurface|USD Preview Surface
usdprimvarreader|USD Prim Var Reader
usdtransform2d|USD Transform 2D
usduvtexture|USD UV Texture
uvcoords|UV Coords
uvnoise|UV Noise
uvplanarproject|UV Planar Project
uvposition|UV Position
uvproject|UV Project
uvtriplanarproject|UV Tri-planar Project
uvxform|UV Transform
vec2getcompon|Get Vector2 Component
vec2setcompon|Set Vector2 Component
vec2tofloat|Vector2 To Float
vec2tohvec|Vector2 To Vector4
vec2tomatx2|Vector2 to Matrix2
vec2tovec|Vector2 To Vector
veccast|Vector Cast
vecgetcompon|Get Vector Component
vecsetcompon|Set Vector Component
vectofloat|Vector To Float
vectohvec|Vector To Vector4
vectomatx|Vector to Matrix3
vectoquat|Vector To Quaternion
vectovec2|Vector to Vector2
veins|Veins
vexvolume|Vex Volume Procedural
vgather|Gather Loop
visualize|Visualize
volumegradientfile|Volume Gradient
volumeindexfile|Volume Index
volumeindextoposfile|Volume Index To Pos
volumeindexvfile|Volume Index Vector
volumepostoindexfile|Volume Pos To Index
volumeresfile|Volume Resolution
volumesamplefile|Volume Sample
volumesamplevfile|Volume Sample Vector
volumeshader|Volume Model
volumevopglobal|Volume VOP Global Parameters
volumevopoutput|Volume VOP Output Variables
vopforceglobal|VOP Force Global
vopforceoutput|VOP Force Output Variables
voronoise|Voronoi Noise
waves|Waves
wavevector|Wave Vector
wire_pattern|Wire Pattern
worleynoise|Worley Noise
xform|Transform Matrix
xor|Xor
xyzdist|XYZ Distance
""",
    "top": """\
attributearray|Attribute Array
attributeclassify|Attribute Classify
attributecopy|Attribute Copy
attributecreate|Attribute Create
attributedelete|Attribute Delete
attributedictionary|Attribute Dictionary
attributefromfile|Attribute from File
attributefromparameters|Attribute from Parameters
attributefromstring|Attribute from String
attributepromote|Attribute Promote
attributerandomize|Attribute Randomize
attributereduce|Attribute Reduce
attributerename|Attribute Rename
attributestringedit|Attribute String Edit
commandserverend|Service Block End
csvinput|CSV Input
csvoutput|CSV Output
deadlinescheduler|Deadline Scheduler
downloadfile|Download File
environmentedit|Environment Edit
error|Error
feedbackbegin|Block Begin Feedback
feedbackend|Block End Feedback
ffmpegencodevideo|FFmpeg Encode Video
ffmpegextractimages|FFmpeg Extract Images
filecompress|File Compress
filecopy|File Copy
filedecompress|File Decompress
filepattern|File Pattern
filerange|File Range
fileremove|File Remove
filerename|File Rename
filterbyattribute|Filter by Attribute
filterbyexpression|Filter by Expression
filterbyrange|Filter by Range
filterbystate|Filter by State
genericgenerator|Generic Generator
geometryimport|Geometry Import
hdaprocessor|HDA Processor
houdiniserver|Houdini Block Begin
hqueuescheduler|HQueue Scheduler
imagemagick|ImageMagick
inprocessscheduler|In Process Scheduler
invoke|Invoke
jsoninput|JSON Input
jsonoutput|JSON Output
labs--archive_project-1.0|Labs Archive Project
labs--concatenate_text-1.0|Labs Concatenate Text
labs--cut_geometry_to_partitions|Labs Cut Geometry to Partitions
labs--data_diff|Labs Data Diff
labs--extract_image_metadata-1.1|Labs Extract Image Metadata
labs--filecachefilter-1.0|Labs File Cache Filter
labs--filecachepartitioner-1.0|Labs File Cache Partitioner
labs--filter_by_value-1.1|Labs Filter by Value
labs--generate_from_imageplanes-1.0|Labs Generate from Imageplanes
labs--ml_cv_rop_synthetic_data-1.1|Labs ML CV ROP Synthetic Data
labs--ropkarma-2.0|Labs Karma Render
labs--topfilecache-2.0|Labs File Cache
labs--wedge-1.0|Labs Wedge
localscheduler|Local Scheduler
makedir|Make Directory
maketx|Make Texture
mayaserver|Maya Block Begin
merge|Merge
ml_preprocesscomputervision|ML Preprocess Computer Vision
ml_preprocessgsplats|ML Preprocess GSplats
ml_preprocessoidn|ML Preprocess OIDN
ml_regressionkernel|ML Regression Kernel
ml_traincomputervision|ML Train Computer Vision
ml_traingsplats|ML Train GSplats
ml_trainneuralcellularautomata|ML Train Neural Cellular Automata
ml_trainoidn|ML Train OIDN
ml_trainregression|ML Train Regression
ml_trainstyletransfer|ML Train Style Transfer
nodepattern|Node Pattern
nukeserver|Nuke Block Begin
null|Null
openimageio|OpenImageIO
opnotify|OP Notify
output|Output
partitionbyattribute|Partition by Attribute
partitionbybounds|Partition by Bounds
partitionbycombination|Partition by Combination
partitionbycomparison|Partition by Comparison
partitionbyexpression|Partition by Expression
partitionbyframe|Partition by Frame
partitionbyindex|Partition by Index
partitionbyiteration|Partition by Iteration
partitionbynode|Partition by Node
partitionbyrange|Partition by Range
partitionbytile|Partition by Tile
perforce|Perforce
preflight|Preflight
pythonpartitioner|Python Partitioner
pythonprocessor|Python Processor
pythonscheduler|Python Scheduler
pythonscript|Python Script
pythonserver|Python Block Begin
pythonvenv|Python Virtual Environment
rangeextend|Range Extend
rangegenerate|Range Generate
remotegraph|Remote Graph
renderifd|Render IFD
ropalembic|ROP Alembic Output
ropcomposite|ROP Composite Output
ropfbx|ROP FBX Output
ropfetch|ROP Fetch
ropflipbook|ROP Flipbook Render
ropgeometry|ROP Geometry Output
ropgltf|ROP GLTF Output
ropimage|ROP Image Output
ropkarma|ROP Karma Render
ropmantra|ROP Mantra Render
ropopengl|ROP OpenGL Render
ropusd|ROP USD Output
sendcommand|Service Block Send
sendemail|Send Email
servicecreate|Service Create
servicedelete|Service Delete
servicereset|Service Reset
servicescheduler|Service Scheduler
servicestart|Service Start
servicestop|Service Stop
shotguncreate|ShotGrid Create
shotgundelete|ShotGrid Delete
shotgundownload|ShotGrid Download
shotgunfind|ShotGrid Find
shotgunserver|ShotGrid Server Begin
shotgunupdate|Shotgun Update
shotgunupload|Shotgun Upload
sort|Sort
split|Split
splitbycount|Split by Count
sqlinput|SQL Input
sqloutput|SQL Output
subnet|Subnetwork
switch|Switch
textoutput|Text Output
topfetch|TOP Fetch
topfetchinput|TOP Fetch Input
tractorscheduler|Tractor Scheduler
urlrequest|URL Request
usdaddassetstogallery|USD Add Assets to Gallery
usdanalyze|USD Analyze
usdimport|USD Import Data
usdimportfiles|USD Import Files
usdmodifypaths|USD Modify Paths
usdrender|USD Render Files
usdrenderscene|USD Render Scene
usdzip|USD Zip
waitforall|Wait for All
wedge|Wedge
workitemexpand|Work Item Expand
workitemimport|Work Item Import
xmlinput|Xml Input
""",
    "chop": """\
acoustic|Acoustic
agent|Agent
area|Area
attribute|Attribute
audioin|Audio In
band|Band EQ
beat|Beat
blend|Blend
blendpose|BlendPose
channel|Channel
channelwrangle|Channel Wrangle
comp|Composite
constant|Constant
constraintblend|Constraint Blend
constraintexport|Export Constraints
constraintgetlocalspace|Constraint Get Local Space
constraintgetparentspace|Constraint Get Parent Space
constraintgetworldspace|Constraint Get World Space
constraintlookat|Constraint Lookat
constraintobject|Constraint Object
constraintobjectoffset|Constraint Object Offset
constraintobjectpretransform|Constraint Object Pretransform
constraintoffset|Constraint Offset
constraintparentx|Constraint Parent
constraintpath|Constraint Path
constraintpoints|Constraint Points
constraintsequence|Constraint Sequence
constraintsimpleblend|Constraint Simple Blend
constraintsurface|Constraint Surface
constrainttransform|Constraint Transform
copy|Copy
count|Count
cycle|Cycle
delay|Delay
delete|Delete
devicetransform|Device Transform
dynamics|Dynamics
dynamicwarp|Dynamic Warp
envelope|Envelope
eulerrotationfilter|Euler Rotation Filter
export|Export
exporttransforms|Export Transforms
express|Expression
extend|Extend
extractbonetransforms|Extract Bone Transforms
extractlocomotion|Extract Locomotion
extractposedrivers|Extract Pose-Drivers
fan|Fan
fbx|FBX
feedback|Feedback
fetch|Fetch Parameters
fetchchop|Fetch Channels
file|File
filter|Filter
footplant|Foot Plant
foreach|Foreach
function|Function
gamepad|Gamepad
geometry|Geometry
gesture|Gesture
handle|Handle
hold|Hold
identity|Identity
iksolver|IKSolver
image|Image
interp|Interpolate
inversekin|InverseKin
invert|Invert
jiggle|Jiggle
keyboard|Keyboard
lag|Lag
layer|Layer
limit|Limit
logic|Logic
lookup|Lookup
math|Math
merge|Merge
midiin|MIDI In
midiout|MIDI Out
mouse|Mouse
mouse3d|Mouse 3D
multiply|Multiply
network|Network
noise|Noise
null|Null
object|Object
objectchain|ObjectChain
oscillator|Oscillator
output|Output
para|Parametric EQ
particle|Particle
pass|Pass Filter
phoneme|Phoneme
pipein|Pipe In
pipeout|Pipe Out
pitch|Pitch
pose|Pose
posedifference|Pose Difference
pretransform|Pretransform
pulse|Pulse
record|Record
rename|Rename
reorder|Reorder
resample|Resample
rop_channel|ROP Channel Output
sequence|Sequence
shift|Shift
shuffle|Shuffle
slope|Slope
spatial|Spatial Audio
spectrum|Spectrum
spline|Spline
spring|Spring
stash|Stash
stashpose|Stash Pose
stretch|Stretch
subnet|Subnetwork
switch|Switch
timerange|Time Range
timeshift|Time Shift
transform|Transform
transformchain|TransformChain
transformvopcvex|Transform VOP CVEX
trigger|Trigger
trim|Trim
vector|Vector
voicesplit|Voice Split
voicesync|Voice Sync
vopchop|Channel VOP
warp|Warp
wave|Wave
waveform|VEX Waveform
""",
    "cop2": """\
labs--attribute_import-1.0|Labs Attribute Import
labs--blackbody_cop|Labs Blackbody
labs--demosaic|Labs Demosaic
labs--grid_texture|Labs Grid Texture
labs--normal_color|Labs Normal Color
labs--normal_combine|Labs Normal Combine
labs--normal_invert|Labs Normal Invert
labs--normal_levels|Labs Normal Levels
labs--normal_map|Labs Normal From Grayscale
labs--normal_normalize|Labs Normalize Normal
labs--normal_rotate|Labs Normal Rotate
labs--sbs_archive|Labs Substance Archive
""",
    "cop": """\
adjacency_attribsample|Attribute Sample with Adjacency
adjacency_distort|Distort with Adjacency
adjacency_extrapolate|Extrapolate with Adjacency
adjacency_spacetransform|Space Transform with Adjacency
align|Align
alignpixels|Align Pixels
attribextract|Attribute Extract
attribfromlayer|Attribute from Layer
attribinsert|Attribute Insert
attribute|Attribute
autostereogram|Auto Stereogram
average|Layer Merge
bakegeometrytextures-2.0|Bake Geometry Textures
bakepreprocess|Bake Pre-Process
bend|Bend
blend|Blend
block_begin|Block Begin
block_end|Block End
blocktogeo|Block to Geometry
blur|Blur
bokeh|Bokeh
boundrect|Bounding Rectangle
bright|Bright
bubblenoise|Bubble Noise
cablefilter|Cable Filter
cablemerge|Cable Merge
cablepack|Cable Pack
cablerename|Cable Rename
cablesort|Cable Sort
cablesplit|Cable Split
cableswitch|Cable Switch
cableunpack|Cable Unpack
cache|Cache
camera|Camera
camerablend|Camera Blend
cameraimport|Camera Import
cameraproperties|Camera Properties
cellpattern|Cell Pattern
cellularnoise|Cellular Noise
cellularnoise3d|Cellular Noise 3D
channelextract|Channel Extract
channeljoin|Channel Join
channelsplit|Channel Split
channelswap|Channel Swap
checkerboard|Checkerboard
chladni|Chladni Cymatic Patterns
chromakey|Chroma Key
chromaticaberration|Chromatic Aberration
clamp|Clamp
cloudnoise3d|Cloud Noise 3D
colorcorrect|Color Correct
combinenormals|Combine Normals
compare|Compare
compareblend|Compare and Blend
configurestamps|Configure Stamps
constant|Constant
contactsheet|Contact Sheet
contrast|Contrast
convertdepth|Convert Depth
convertnormal|Convert Normal
convolve3|Convolve 3×3
convolvefilter|Convolve Filter
copyxform|Copy and Transform
cornerdetect|Corner Detect
cornerpin|Corner Pin
crop|Crop
cross|Cross Product
cryptomatte|Cryptomatte
cryptomattedecode|Cryptomatte Decode
cryptomatteencode|Cryptomatte Encode
crystalnoise|Crystal Noise
crystalnoise3d|Crystal Noise 3D
curl|Curl
curlnoise|Curl Noise
curlnoise3d|Curl Noise 3D
curvature|Curvature
curve3d|Curve 3D
curveanimate3d|Curve Animate 3D
curvescatter|Scatter on Curves
defocus|Defocus
denoiseai|Denoise AI
denoisetvd|Denoise TVD
derivative|Derivative
despill|Despill
dilateerode|Dilate Erode
distort|Distort
dot|Dot Product
dropshadow|Drop Shadow
edgedetect|Edge Detect
edgedetectcontour|Edge Detect by Contour
edgedetectdepth|Edge Detect by Depth
edgedetectnormal|Edge Detect by Normal
eikonal|Eikonal
equalize|Equalize
error|Error
extrapolateboundaries|Extrapolate Boundaries
feather|Feather
fetch|Fetch
fft|Fast Fourier Transform
file|File
fill|Fill
fillconnected|Fill Connected
filterfrequencies|Filter Frequencies
flip|Flip
flow_block_begin|Flow Block Begin
flow_block_end|Flow Block End
flow_projectnondivergentmultigrid|Flow Project Non-Divergent Multigrid
font|Font
fractalnoise|Fractal Noise
fractalnoise3d|Fractal Noise 3D
fractalsample|Fractal Sample
function|Function
gamma|Gamma
geoattribfromlayer|Geometry Attribute from Layer
geotoadjacency|Geometry to Adjacency
geotolayer-2.0|Geometry to Layer
glow|Glow
grunge_aurora|Grunge Aurora
grunge_barkstrips|Grunge Bark Strips
grunge_birchbark|Grunge Birch Bark
grunge_drips|Grunge Drips
grunge_galvanizedsteel|Grunge Galvanized Steel
grunge_layerednoise|Grunge Layered Noise
grunge_leakingstreaks|Grunge Leaking Streaks
grunge_moisture|Grunge Moisture
grunge_moldspots|Grunge Mold Spots
grunge_pinebark|Grunge Pine Bark
grunge_rust|Grunge Rust
grunge_rustysurface|Grunge Rusty Surface
grunge_sheets|Grunge Sheets
grunge_wipetrails|Grunge Wipe Trails
heatdistort|Heat Distort
heatdistortbylayer|Heat Distort by Layer
heightfield_clip|HeightField Clip
heightfield_erode|HeightField Erode
heightfield_maskbyfeature|HeightField Mask by Feature
heightfield_project|HeightField Project
heightfield_slump|HeightField Slump
heightfield_strata|HeightField Strata
heightfield_terrace|HeightField Terrace
heightfield_visualize|HeightField Visualize
heightfield_xform|HeightField Transform 3D
heightfield_xform2d|HeightField Transform 2D
heightfieldtomono|HeightField to Mono
heighttoambientocclusion|Height to Ambient Occlusion
heighttocaustics|Height to Caustics
heighttonormal|Height to Normal
heighttoshadow|Height to Shadow
hextile|Hex Tile
histogram|Histogram
hsv|HSV Adjust
hyperbolictile|Hyperbolic Tile
idtomask|ID to Mask
idtomono|ID to Mono
idtorgb|ID to RGB
idtosdf|ID to SDF
illpixel|Illegal Pixel
input|Input
integratevolume|Integrate Volume
invert|Invert
invokeblock|Invoke Block
invokegeo|Invoke Geometry
julia|Julia Fractal
knit|Knit
kuwaharafilter|Kuwahara Filter
labs--cluster_colors-1.0|Labs Cluster Colors
labs--physical_star_glow-1.0|Labs Physical Star Glow
labs--uv_grid_texture-1.1|Labs UV Grid Texture
laplacian|Laplacian
latticedeform|Lattice Deform
layer|Layer
layerattribcreate|Layer Property Create
layerattribdelete|Layer Property Delete
layerfromattrib|Layer from Attribute
layerfromcurves|Layer from Curves
layerfromvdb|Layer from VDB
layerproperties|Layer Properties
layerpropertycopy|Layer Property Copy
layertogeo-2.0|Layer to Geometry
layertopoints|Layer to Points
layertovdbleafpoints|Layer to VDB Leaf Points
lensdistort|Lens Distort
light|Light
livevideo|Live Video
logic|Logic
maskcombine|Mask Combine
maskfromcurves|Mask from Curves
matchcamera|Match Camera
matchudim|Match UDIM
median|Median
mirror|Mirror
ml_computervisioninference|ML Computer Vision Inference
mono|Mono
monotoheightfield|Mono to HeightField
monotoid|Mono to ID
monotorgb|Mono to RGB
monotorgba|Mono to RGBA
monotosdf|Mono to SDF
neural_cellularautomatacore|Neural Cellular Automata Core
neural_cellularautomatadecode|Neural Cellular Automata Decode
neural_layertodepth_moge2|Neural Layer to Depth (MoGe-2)
neural_layertomask_sam2|Neural Layer to Mask (SAM2)
normaltoheight|Normal to Height
null|Null
oceanevaluate|Ocean Evaluate
oceanspectrum|Ocean Spectrum
ociotransform|OCIO Transform
onnx|ONNX Inference
opencl|OpenCL
output|Output
paint|Paint 3D
phasornoise|Phasor Noise
pixelate|Pixelate
planarinflate|Planar Inflate
pointdelete|Point Delete
pointgenerate|Point Generate
pointmerge|Point Merge
pointsfromblobs|Points from Blobs
polartouv|Polar to UV
posmap|Position Map
possample|Position Sample
prefixsum|Prefix Sum
premult|Premultiply
previewmaterial|Preview Material
projectonlayer|Project on Layer
pyro_activate|Pyro Activate
pyro_advect|Pyro Advect
pyro_advectbymap|Pyro Advect by Map
pyro_axisforce|Pyro Axis Force
pyro_block_begin|Pyro Block Begin
pyro_block_end|Pyro Block End
pyro_buildadvectionmap|Pyro Build Advection Map
pyro_buoyancy|Pyro Buoyancy Force
pyro_collisionfromshape|Pyro Collision from Shape
pyro_collisionshape|Pyro Collision Shape
pyro_configure|Pyro Configure
pyro_dissipate|Pyro Dissipate
pyro_disturbance|Pyro Disturbance
pyro_emitfromflame|Pyro Emit from Flame
pyro_lightambient|Pyro Light Ambient
pyro_lightfrompoints|Pyro Light from Points
pyro_lightscatter|Pyro Light Scatter
pyro_packedmipmap|Pyro Packed MipMap
pyro_projectnondivergentelectrostatic|Pyro Project Non-Divergent Electro Static
pyro_sourcefromlayer|Pyro Source from Layer
pyro_sourcefrompoints|Pyro Source from Points
pyro_sourcefromshape|Pyro Source from Shape
pyro_sourcefromvolume|Pyro Source from Volume
pyro_sourceshape|Pyro Source Shape
pyro_turbulence|Pyro Turbulence
pyro_uniformforce|Pyro Uniform Force
pyro_velocityscale|Pyro Velocity Scale Force
pyro_vortexconfinement|Pyro Vortex Confinement Force
pythonsnippet|Python Snippet
quantize|Quantize
ramp|Ramp
randommono|Random Mono
randomrgb|Random RGB
rasterizecurves|Rasterize Curves
rasterizegeo|Rasterize Geometry
rasterizegsplats|Rasterize GSplats
rasterizeimplicitsurface|Rasterize Implicit Surface
rasterizelayer|Rasterize Layer
rasterizesetup|Rasterize Setup
rasterizevolume|Rasterize Volume
raytrace|Ray Trace
reactiondiffusion_block_begin|Reaction-Diffusion Block Begin
reactiondiffusion_block_end|Reaction-Diffusion Block End
refractfromheight|Refract from Height
remap|Remap
resample|Resample
rgbatorgb|RGBA to RGB
rgbatouv|RGBA to UV
rgbtorgba|RGB to RGBA
rgbtouv|RGB to UV
ripple_block_begin|Ripple Block Begin
ripple_block_end|Ripple Block End
rop_image|ROP Image
sample|UV Sample
sdfadjust|SDF Adjust
sdfblend|SDF Blend
sdfshape|SDF Shape
sdftomono|SDF to Mono
sdftorgb|SDF to RGB
segmentbyconnectivity|Segment by Connectivity
segmentbyvalue|Segment by Value
sequence|Sequence
sequenceblend|Sequence Blend
shapescatter|Scatter Shapes
sharpen|Sharpen
slapcompimport|Slap Comp Import
slopedir|Slope Direction
smoothfill|Smooth Fill
solvepoisson|Solve Poisson
solvepoissonmultigrid|Solve Poisson Multigrid
sopimport|SOP Import
sopinvoke|SOP Invoke
sopinvokegraph|SOP Invoke Graph
spacetransform|Space Transform
spheresample|Sphere Sample
stamppoint|Stamp Points
starglow|Star Glow
stash|Stash
statistics|Statistics
statisticsbyid|Statistics by ID
streakblur|Streak Blur
subnet|Subnetwork
surfacedither|Surface Dither
swirl|Swirl
switch|Switch
switchbytype|Switch by Type
switchifwired|Switch If Wired
testgeometry_capybara|Test Geometry: Capybara
testgeometry_otto|Test Geometry: Otto
testgeometry_pighead|Test Geometry: Pig Head
testgeometry_rubbertoy|Test Geometry: Rubber Toy
testgeometry_shaderball|Test Geometry: Shader Ball
testgeometry_squab|Test Geometry: Squab
testgeometry_tommy|Test Geometry: Tommy
tilepattern|Tile Pattern
timeblend|Time Blend
timeloop|Time Loop
timepack|Time Pack
timeshift|Time Shift
tonemap|Tone Map
triplanar|Triplanar
triplanarhextile|Triplanar Hex Tile
triplanaruv|Triplanar UV
turingpatterns|Turing Patterns
twowayswitchifwired|Two Way Switch If Wired
udimpack|UDIM Pack
usdmaterial|USD Material
uvinverse|UV Inverse
uvmap|UV Map
uvmapbyid|UV Map by ID
uvshape|UV Shape
uvtopolar|UV to Polar
uvtorgb|UV to RGB
uvtorgba|UV to RGBA
uvxform|UV Transform
vdbactivatefrompoints|VDB Activate from Points
vdbfromlayer|VDB from Layer
vdbleafpoints|VDB Leaf Points
vdbposmap|VDB Position Map
vdbreshape|VDB Reshape
vdbvisualize|VDB Visualize
vdbvisualizeslice|VDB Visualize Slice
vdbvisualizetree|VDB Visualize Tree
vdbvisualizevelocity|VDB Visualize Velocity
vectorxform|Vector Transform
vectorxform2d|Vector Transform 2D
vignette|Vignette
visualizevelocity|Visualize Velocity
weave|Weave
wipe|Wipe
worleynoise|Worley Noise
worleynoise3d|Worley Noise 3D
wrangle|Wrangle
xform|Transform 3D
xform2d|Transform 2D
zcomp|Z Composite
""",
    "out": """\
agent|Agent
alembic|Alembic
alf|Tractor
archive|Archive Generator
bake_animation|Bake Animation
baketexture|Bake Texture
batch|Batch
channel|Channel
comp|Composite
dembones_skinningconverter|Dem Bones Skinning Converter
dop|Dynamics
dsmmerge|DSM Merge
fetch|Fetch
filmboxfbx|Filmbox FBX
flipbook|Flipbook
framecontainer|Frame Container
framedep|Frame Depedency
geometry|Geometry
geometryraw|Geometry Raw
gltf|glTF 2.0
haircardtex|Hair Card Texture
hq_render|HQueue Render
hq_sim|HQueue Simulation
ifd|Mantra
ifdarchive|Mantra Archive
image|Image
karma|Karma
kinefx--filmboxfbxanimation|Filmbox FBX Animation
kinefx--filmboxfbxcharacter|Filmbox FBX Character
kinefx--gltfcharacter|GLTF Character
labs--3d_facebook_image|Labs 3D Facebook Image
labs--csv_exporter|Labs CSV Exporter
labs--flipbook_textures-1.0|Labs Flipbook Textures
labs--json_exporter-1.0|Labs JSON Exporter
labs--marmoset_export-1.0|Labs Marmoset Export
labs--niagara_rop|Labs Niagara ROP
labs--pyro_preview|Labs Pyro Preview ROP
labs--rbd_to_fbx-3.0|Labs RBD to FBX
labs--sketchfab|Labs Sketchfab
labs--vertex_animation_textures-4.0|Labs Vertex Animation Textures
labs--xyz_pointcloud_exporter|Labs XYZ Pointcloud Exporter
labs--zibravdb_compress-1.0|Labs ZibraVDB Compress
mdd|MDD Point Cache
merge|Merge
ml_exampleraw|ML Example Raw
netbarrier|Net Barrier
null|Null
prepost|Pre Post
shell|Shell
subnet|Subnetwork
switch|Switch
usd|USD
usdrender|USD Render
usdstitch|USD Stitch
usdstitchclips|USD Stitch Clips
usdzip|USD Zip
wedge|Wedge
wren|Wren
""",
    "apex": """\
Acos|Acos
And|And
Asin|Asin
Atan|Atan
Atan2|Atan2
BitwiseAnd|BitwiseAnd
BitwiseNot|BitwiseNot
BitwiseOr|BitwiseOr
BitwiseXor|BitwiseXor
BoolToIntBitMask|BoolToIntBitMask
Break|Break
CartesianToGeodetic|CartesianToGeodetic
CartesianToPolar|CartesianToPolar
CartesianToSpherical|CartesianToSpherical
Ceil|Ceil
Complement|Complement
ComponentBoolsToInt|ComponentBoolsToInt
ComponentIntToBools|ComponentIntToBools
Continue|Continue
CopyArg|CopyArg
Cosine|Cosine
CrossProduct|CrossProduct
DragPlane|DragPlane
Efit|Efit
Exponential|Exponential
Fit|Fit
Fit01|Fit01
Fit10|Fit10
Fit11|Fit11
FloatToVector2|FloatToVector2
FloatToVector3|FloatToVector3
FloatToVector4|FloatToVector4
Floor|Floor
ForBegin|ForBegin
ForEnd|ForEnd
ForRangeBegin|ForRangeBegin
ForRangeEnd|ForRangeEnd
Fps|Fps
Frac|Frac
Frame|Frame
FrameEnd|FrameEnd
FrameStart|FrameStart
GeodeticToCartesian|GeodeticToCartesian
IfBegin|IfBegin
IfEnd|IfEnd
IntBitMaskToBool|IntBitMaskToBool
Log|Log
Logarithm|Logarithm
Matrix3ToVector3|Matrix3ToVector3
Matrix4ToVector4|Matrix4ToVector4
Modulo|Modulo
Not|Not
Or|Or
PolarToCartesian|PolarToCartesian
Power|Power
Round|Round
RunVex|RunVex
Sine|Sine
SphericalToCartesian|SphericalToCartesian
Tan|Tan
Time|Time
TimeStep|TimeStep
TransformObject|TransformObject
Vector2ToFloat|Vector2ToFloat
Vector3ToFloat|Vector3ToFloat
Vector3ToMatrix3|Vector3ToMatrix3
Vector4ToFloat|Vector4ToFloat
Vector4ToMatrix4|Vector4ToMatrix4
Xor|Xor
__null__|Null
__output__|Output
__parms__|Input
__subnet__|Subnetwork
array--Range|array::Range
ch--AddKey|ch::AddKey
ch--AddKeys|ch::AddKeys
ch--AnimStackAddKey|ch::AnimStackAddKeys
ch--AnimStackBuild|ch::AnimStackBuild
ch--AnimStackEvaluate|ch::AnimStackEvaluate
ch--BlendKeys|ch::BlendKeys
ch--ChannelCollectionFromPrims|ch::ChannelCollectionFromPrims
ch--ChannelFromCollection|ch::ChannelFromCollection
ch--ChannelFromFloatArray|ch::ChannelFromFloatArray
ch--ChannelFromPrim|ch::ChannelFromPrim
ch--ChannelToFloatArray|ch::ChannelToFloatArray
ch--ChannelToPoints|ch::ChannelToPoints
ch--ChannelToPrim|ch::ChannelToPrim
ch--ChannelsFromCollection|ch::ChannelsFromCollection
ch--ChannelsFromPrims|ch::ChannelsFromPrims
ch--CollectionBlendKeys|ch::CollectionBlendKeys
ch--CollectionCopyKeys|ch::CollectionCopyKeys
ch--CollectionCycleKeys|ch::CollectionCycleKeys
ch--CollectionDeleteKeys|ch::CollectionDeleteKeys
ch--CollectionEulerFilter|ch::CollectionEulerFilter
ch--CollectionGetChannel|ch::CollectionGetChannel
ch--CollectionGetChannelArray|ch::CollectionGetChannelArray
ch--CollectionLength|ch::CollectionLength
ch--CollectionNameAt|ch::CollectionNameAt
ch--CollectionNames|ch::CollectionNames
ch--CollectionReduceKeys|ch::CollectionReduceKeys
ch--CollectionScaleKeys|ch::CollectionScaleKeys
ch--CollectionSetChannel|ch::CollectionSetChannel
ch--CollectionSetChannelArray|ch::CollectionSetChannelArray
ch--CollectionSetChannels|ch::CollectionSetChannels
ch--CollectionShiftKeys|ch::CollectionShiftKeys
ch--CollectionSmoothAutoTangents|ch::CollectionSmoothAutoTangents
ch--CollectionSmoothKeys|ch::CollectionSmoothKeys
ch--CopyKeys|ch::CopyKeys
ch--CycleKeys|ch::CycleKeys
ch--DeleteKeys|ch::DeleteKeys
ch--DictUpdateFromChannelGeo|ch::DictUpdateFromChannelGeo
ch--EulerFilter|ch::EulerFilter
ch--Evaluate|ch::Evaluate
ch--EvaluateLayered|ch::EvaluateLayered
ch--EvaluateMulti|ch::EvaluateMulti
ch--PrimsFromChannelCollection|ch::PrimsFromChannelCollection
ch--ReduceKeys|ch::ReduceKeys
ch--ScaleKeys|ch::ScaleKeys
ch--ShiftKeys|ch::ShiftKeys
ch--SmoothAutoTangents|ch::SmoothAutoTangents
ch--SmoothKeys|ch::SmoothKeys
component--AddAbstractControl|component::AddAbstractControl
component--AddConfigControl|component::AddConfigControl
component--AddControlAction|component::AddControlAction
component--AddControlGroup|component::AddControlGroup
component--AddControlGroupPrimary|component::AddControlGroupPrimary
component--AddIkInverter|component::AddIkInverter
component--AddSpaceSwitchControl|component::AddSpaceSwitchControl
component--AddSplineInverter|component::AddSplineInverter
component--Blendshape|component::Blendshape
component--Bonedeform|component::Bonedeform
component--ChannelToPort|component::ChannelToPort
component--ConnectPorts|component::ConnectPorts
component--Deltamush|component::Deltamush
component--FBIK|component::FBIK
component--FKIK|component::FKIK
component--FindSegments|component::FindSegments
component--GetRestTransform|component::GetRestTransform
component--GetRig|component::GetRig
component--GetTransformChildren|component::GetTransformChildren
component--GetTransformDescendants|component::GetTransformDescendants
component--GetTransformParent|component::GetTransformParent
component--InsertTransformParent|component::InsertTransformParent
component--Lookat|component::Lookat
component--MappedConstraints|component::MappedConstraints
component--MultiIk|component::MultiIk
component--PlaceSpline|component::PlaceSpline
component--ProcessSegment|component::ProcessSegment
component--Rename|component::Rename
component--ReverseFoot|component::ReverseFoot
component--SetRestTransform|component::SetRestTransform
component--SetRestTransformFromSkel|component::SetRestTransformFromSkel
component--SetTransformParent|component::SetTransformParent
component--Spline|component::Spline
component--Spline2|component::Spline2
component--TransformDriver|component::TransformDriver
component--Twist|component::Twist
component--UnpromoteControl|component::UnpromoteControl
component--UpdateControls|component::UpdateControls
component--UpdateParmLimits|component::UpdateParmLimits
component--UpdateRig|component::UpdateRig
dict--Build|dict::Build
dict--Clear|dict::Clear
dict--Contains|dict::Contains
dict--DebugDataIds|dict::DebugDataIds
dict--Extract|dict::Extract
dict--Insert|dict::Insert
dict--Keys|dict::Keys
dict--PatternRenameKeys|dict::PatternRenameKeys
dict--Remove|dict::Remove
dict--RenameKeys|dict::RenameKeys
dict--Transfer|dict::Transfer
dict--Update|dict::Update
dynamicpath--Add|dynamicpath::Add
dynamicpath--AddTweakTarget|dynamicpath::AddTweakTarget
dynamicpath--Bake|dynamicpath::Bake
dynamicpath--DeformLaplacian|dynamicpath::DeformLaplacian
dynamicpath--Evaluate|dynamicpath::Evaluate
dynamicpath--EvaluateInSourceTime|dynamicpath::EvaluateInSourceTime
dynamicpath--EvaluateMulti|dynamicpath::EvaluateMulti
dynamicpath--EvaluateMultiInSourceTime|dynamicpath::EvaluateMultiInSourceTime
dynamicpath--GetAllSections|dynamicpath::GetAllSections
dynamicpath--GetKeyTimes|dynamicpath::GetKeyTimes
dynamicpath--GetSection|dynamicpath::GetSection
dynamicpath--GetTiming|dynamicpath::GetTiming
dynamicpath--LoadFromAnimStack|dynamicpath::LoadFromAnimStack
dynamicpath--LoadFromArray|dynamicpath::LoadFromArray
dynamicpath--LoadFromChannels|dynamicpath::LoadFromChannels
dynamicpath--LoadFromGeometry|dynamicpath::LoadFromGeometry
dynamicpath--LoadFromGraph|dynamicpath::LoadFromGraph
dynamicpath--LoadFromGraphChannels|dynamicpath::LoadFromGraphChannels
dynamicpath--ProjectileLifeFromPlane|dynamicpath::ProjectileLifeFromPlane
dynamicpath--ProjectilePathEvaluatePeak|dynamicpath::ProjectilePathEvaluatePeak
dynamicpath--ProjectilePathFromLife|dynamicpath::ProjectilePathFromLife
dynamicpath--ProjectilePathFromPlane|dynamicpath::ProjectilePathFromPlane
dynamicpath--ProjectilePathFromSpeed|dynamicpath::ProjectilePathFromSpeed
dynamicpath--ResolveTweakTargets|dynamicpath::ResolveTweakTargets
dynamicpath--SaveToGeometry|dynamicpath::SaveToGeometry
dynamicpath--Subtract|dynamicpath::Subtract
fbik--GetBoneTransform|fbik::GetBoneTransform
fbik--GetCenterOfMass|fbik::GetCenterOfMass
fbik--SetComTarget|fbik::SetComTarget
fbik--SetSkeleton|fbik::SetSkeleton
fbik--SetTarget|fbik::SetTarget
fbik--SetTargets|fbik::SetTargets
fbik--SetTargetsFromDict|fbik::SetTargetsFromDict
fbik--SetTargetsFromGeo|fbik::SetTargetsFromGeo
fbik--SkeletonFromGeo|fbik::SkeletonFromGeo
fbik--SkeletonUpdateGeo|fbik::SkeletonUpdateGeo
fbik--SolveFABRIK|fbik::SolveFABRIK
fbik--SolvePhysIK|fbik::SolvePhysIK
fbik--Solver|fbik::Solver
fbik--Target|fbik::Target
geo--AddPacked|geo::AddPacked
geo--AttribIntersectPoints|geo::AttribIntersectPoints
geo--BoundingBox|geo::BoundingBox
geo--CopyDetailAttrib|geo::CopyDetailAttrib
geo--DetailAttribData|geo::DetailAttribData
geo--ExtractPackedGeo|geo::ExtractPackedGeo
geo--ExtractPackedPaths|geo::ExtractPackedPaths
geo--ForEachPointBegin|geo::ForEachPointBegin
geo--ForEachPointEnd|geo::ForEachPointEnd
geo--ForEachPrimBegin|geo::ForEachPrimBegin
geo--ForEachPrimEnd|geo::ForEachPrimEnd
geo--FromDisk|geo::FromDisk
geo--GetCameraProperties|geo::GetCameraProperties
geo--GetCameraTransforms|geo::GetCameraTransforms
geo--GlobPoints|geo::GlobPoints
geo--GlobPrims|geo::GlobPrims
geo--GuideDeform|geo::GuideDeform
geo--InPointGroup|geo::InPointGroup
geo--InPrimGroup|geo::InPrimGroup
geo--InVertexGroup|geo::InVertexGroup
geo--InitIntersectCache|geo::InitIntersectCache
geo--Intersect|geo::Intersect
geo--IntersectPoints|geo::IntersectPoints
geo--JigglePointAttribs|geo::JigglePointAttribs
geo--LagOvershootPointAttribs|geo::LagOvershootPointAttribs
geo--Lattice|geo::Lattice
geo--Merge|geo::Merge
geo--MergePacked|geo::MergePacked
geo--NameToPrim|geo::NameToPrim
geo--NumPoints|geo::NumPoints
geo--NumPrims|geo::NumPrims
geo--PointAttribData|geo::PointAttribData
geo--PointPrims|geo::PointPrims
geo--PrimAttribData|geo::PrimAttribData
geo--PrimPoints|geo::PrimPoints
geo--Replace|geo::Replace
geo--SetAgentTransforms|geo::SetAgentTransforms
geo--SetCameraProperties|geo::SetCameraProperties
geo--SetCameraTransforms|geo::SetCameraTransforms
geo--SetCameraTransformsFromSkel|geo::SetCameraTransformsFromSkel
geo--SetPointGroup|geo::SetPointGroup
geo--SetPrimGroup|geo::SetPrimGroup
geo--SetVertexGroup|geo::SetVertexGroup
geo--SpringPointAttribs|geo::SpringPointAttribs
geo--Transform|geo::Transform
geo--UpdatePackedGeo|geo::UpdatePackedGeo
geo--VertexAttribData|geo::VertexAttribData
geo--XyzDist|geo::XyzDist
geoutils--CopyToPointsTargetAttribs|geoutils::CopyToPointsTargetAttribs
geoutils--DottedLine|geoutils::DottedLine
geoutils--Translate|geoutils::Translate
geoutils--UniformScale|geoutils::UniformScale
geoutils--UpdateCameraProperties|geoutils::UpdateCameraProperties
geoutils--Wrangle|geoutils::Wrangle
graph--AddNode|graph::AddNode
graph--AddNodeToSubnet|graph::AddNodeToSubnet
graph--AddOrUpdateNode|graph::AddOrUpdateNode
graph--AddSubnet|graph::AddSubnet
graph--AddTime|graph::AddTime
graph--Compile|graph::Compile
graph--ConnectInput|graph::ConnectInput
graph--DefaultParms|graph::DefaultParms
graph--DeleteNode|graph::DeleteNode
graph--DeleteNodes|graph::DeleteNodes
graph--DisconnectPort|graph::DisconnectPort
graph--DuplicateNode|graph::DuplicateNode
graph--EvaluateOutputs|graph::EvaluateOutputs
graph--FindAndConnectInput|graph::FindAndConnectInput
graph--FindAndRemoveWire|graph::FindAndRemoveWire
graph--FindFirstNode|graph::FindFirstNode
graph--FindFirstPort|graph::FindFirstPort
graph--FindNode|graph::FindNode
graph--FindNodeInput|graph::FindNodeInput
graph--FindNodeOutput|graph::FindNodeOutput
graph--FindNodeTags|graph::FindNodeTags
graph--FindNodes|graph::FindNodes
graph--FindOrAddNode|graph::FindOrAddNode
graph--FindOrAddPort|graph::FindOrAddPort
graph--FindPort|graph::FindPort
graph--FindPorts|graph::FindPorts
graph--FindUniqueNodeName|graph::FindUniqueNodeName
graph--GetConnectedNodes|graph::GetConnectedNodes
graph--GetConnectedPort|graph::GetConnectedPort
graph--GetConnectedPorts|graph::GetConnectedPorts
graph--GetPromotedPort|graph::GetPromotedPort
graph--GetSubPort|graph::GetSubPort
graph--GetSubnetContents|graph::GetSubnetContents
graph--GraphInputs|graph::GraphInputs
graph--GraphOutputs|graph::GraphOutputs
graph--HasNodeTag|graph::HasNodeTag
graph--HasNodeTags|graph::HasNodeTags
graph--Invoke|graph::Invoke
graph--IsConnected|graph::IsConnected
graph--Layout|graph::Layout
graph--LoadFromGeometry|graph::LoadFromGeometry
graph--Merge|graph::Merge
graph--NodeData|graph::NodeData
graph--NodeInput|graph::NodeInput
graph--NodeInputs|graph::NodeInputs
graph--NodeOutput|graph::NodeOutput
graph--NodeOutputs|graph::NodeOutputs
graph--PackSubnet|graph::PackSubnet
graph--ParentNodes|graph::ParentNodes
graph--PortData|graph::PortData
graph--PortNode|graph::PortNode
graph--PromoteInput|graph::PromoteInput
graph--PromoteNodeInput|graph::PromoteNodeInput
graph--PromoteNodeInputs|graph::PromoteNodeInputs
graph--PromoteNodeOutput|graph::PromoteNodeOutput
graph--PromoteNodeOutputs|graph::PromoteNodeOutputs
graph--PromoteOutput|graph::PromoteOutput
graph--PromotePort|graph::PromotePort
graph--Properties|graph::Properties
graph--RemoveNodeTag|graph::RemoveNodeTag
graph--RenameNode|graph::RenameNode
graph--RenamePort|graph::RenamePort
graph--ReplaceNodeTag|graph::ReplaceNodeTag
graph--RewireOutputs|graph::RewireOutputs
graph--SaveToGeometry|graph::SaveToGeometry
graph--SetDefaultParms|graph::SetDefaultParms
graph--SetNodeColor|graph::SetNodeColor
graph--SetNodeTag|graph::SetNodeTag
graph--SetProperties|graph::SetProperties
graph--SetSubnetContents|graph::SetSubnetContents
graph--Sort|graph::Sort
graph--Template|graph::Template
graph--UnpackSubnet|graph::UnpackSubnet
graph--UpdateControls|graph::UpdateControls
graph--UpdateNode|graph::UpdateNode
graph--UpdateNodeParms|graph::UpdateNodeParms
graph--UpdateNodeProperties|graph::UpdateNodeProperties
graph--UpdateNodeTags|graph::UpdateNodeTags
graphutils--AcceptsSubport|graphutils::AcceptsSubport
graphutils--NodeAncestors|graphutils::NodeAncestors
graphutils--NodeCallbackName|graphutils::NodeCallbackName
graphutils--NodeName|graphutils::NodeName
graphutils--NodeParent|graphutils::NodeParent
graphutils--NodeParms|graphutils::NodeParms
graphutils--NodePath|graphutils::NodePath
graphutils--NodeProperties|graphutils::NodeProperties
graphutils--NodeTags|graphutils::NodeTags
graphutils--OuterPort|graphutils::OuterPort
graphutils--PortPath|graphutils::PortPath
guide--AddSetPointTransforms|guide::AddSetPointTransforms
guide--ControlsFromGuides|guide::ControlsFromGuides
guide--FindOrAddGuide|guide::FindOrAddGuide
guide--FindPrimaryAxis|guide::FindPrimaryAxis
guide--SetGuideParent|guide::SetGuideParent
guide--SetGuideProperties|guide::SetGuideProperties
guide--UpdatePatternFromGuides|guide::UpdatePatternFromGuides
guide--UpdateShapesFromGuides|guide::UpdateShapesFromGuides
quaternion--Distance|quaternion::Distance
quaternion--Exponential|quaternion::Exponential
quaternion--FromAxisAngle|quaternion::FromAxisAngle
quaternion--FromEuler|quaternion::FromEuler
quaternion--Invert|quaternion::Invert
quaternion--Logarithm|quaternion::Logarithm
quaternion--Multiply|quaternion::Multiply
quaternion--Power|quaternion::Power
quaternion--Rotate|quaternion::Rotate
quaternion--SwingTwistInterpolate|quaternion::SwingTwistInterpolate
quaternion--ToAxisAngle|quaternion::ToAxisAngle
quaternion--ToEuler|quaternion::ToEuler
ragdoll--Solve|ragdoll::Solve
ragdoll--Turbulence|ragdoll::Turbulence
rig--AbstractControl|rig::AbstractControl
rig--AddControlShape|rig::AddControlShape
rig--CombineParmTransform|rig::CombineParmTransform
rig--ControlRigExtract|rig::ControlRigExtract
rig--ControlRigExtractSkel|rig::ControlRigExtractSkel
rig--ControlShape|rig::ControlShape
rig--ControlSpline|rig::ControlSpline
rig--ControlSplineFromArray|rig::ControlSplineFromArray
rig--CurveConstraint|rig::CurveConstraint
rig--ExtractLocalTransform|rig::ExtractLocalTransform
rig--ExtractParmTransform|rig::ExtractParmTransform
rig--FkTransform|rig::FkTransform
rig--MultiBoneIK|rig::MultiBoneIK
rig--MultiBoneIKFromArray|rig::MultiBoneIKFromArray
rig--ParentBlend|rig::ParentBlend
rig--PointConstraint|rig::PointConstraint
rig--PoseWeightInterpolation|rig::PoseWeightInterpolation
rig--PrimConstraint|rig::PrimConstraint
rig--RBFInterpolation|rig::RBFInterpolation
rig--SampleSplineTransforms|rig::SampleSplineTransforms
rig--SampleSplineTransformsToArray|rig::SampleSplineTransformsToArray
rig--SplineInterpolateTransforms|rig::SplineInterpolateTransforms
rig--SplineInterpolateTransformsToArray|rig::SplineInterpolateTransformsToArray
rig--SplineOffset|rig::SplineOffset
rig--SplineOffsets|rig::SplineOffsets
rig--SplineOffsetsToArray|rig::SplineOffsetsToArray
rig--TwoBoneIK|rig::TwoBoneIK
rig--UVConstraint|rig::UVConstraint
sim--CreateObject|sim::CreateObject
sim--CreateRelationship|sim::CreateRelationship
sim--CreateSubData|sim::CreateSubData
sim--EvaluateAtTime|sim::EvaluateAtTime
sim--FindObject|sim::FindObject
sim--FindRelationship|sim::FindRelationship
sim--GetGeometry|sim::GetGeometry
sim--LoadSimFile|sim::LoadSimFile
sim--RemoveObject|sim::RemoveObject
sim--RemoveRelationship|sim::RemoveRelationship
sim--SetGeometry|sim::SetGeometry
sim--SimEngine|sim::SimEngine
skel--AddJoint|skel::AddJoint
skel--Blend|skel::Blend
skel--DeleteJoint|skel::DeleteJoint
skel--DeleteJoints|skel::DeleteJoints
skel--EvaluateMotionClip|skel::EvaluateMotionClip
skel--EvaluateMotionClipArray|skel::EvaluateMotionClipArray
skel--FindFirstJoint|skel::FindFirstJoint
skel--FindJoint|skel::FindJoint
skel--FindJoints|skel::FindJoints
skel--FindRoots|skel::FindRoots
skel--GetAncestors|skel::GetAncestors
skel--GetChildren|skel::GetChildren
skel--GetDescendants|skel::GetDescendants
skel--GetParent|skel::GetParent
skel--GetPointLocalTransform|skel::GetPointLocalTransform
skel--GetPointLocalTransforms|skel::GetPointLocalTransforms
skel--GetPointTransform|skel::GetPointTransform
skel--GetPointTransforms|skel::GetPointTransforms
skel--JointData|skel::JointData
skel--OrientJoints|skel::OrientJoints
skel--SetParent|skel::SetParent
skel--SetParents|skel::SetParents
skel--SetPointTransforms|skel::SetPointTransforms
skel--SetPointTransformsFromAgent|skel::SetPointTransformsFromAgent
skel--SmoothMotion|skel::SmoothMotion
skel--SmoothMotionArray|skel::SmoothMotionArray
skel--SmoothMotionClip|skel::SmoothMotionClip
skel--Sort|skel::Sort
skel--Traverse|skel::Traverse
skel--UpdateJoint|skel::UpdateJoint
string--CamelCase|string::CamelCase
string--EndsWith|string::EndsWith
string--Expand|string::Expand
string--Find|string::Find
string--ForceValidName|string::ForceValidName
string--Format|string::Format
string--FromInteger|string::FromInteger
string--Join|string::Join
string--Length|string::Length
string--Lower|string::Lower
string--Partition|string::Partition
string--PathSplit|string::PathSplit
string--PatternRename|string::PatternRename
string--RegexFind|string::RegexFind
string--RegexFindAll|string::RegexFindAll
string--RegexMatch|string::RegexMatch
string--RegexReplace|string::RegexReplace
string--RegexSplit|string::RegexSplit
string--Replace|string::Replace
string--Reverse|string::Reverse
string--Slice|string::Slice
string--Split|string::Split
string--StartsWith|string::StartsWith
string--SubString|string::SubString
string--ToFloat|string::ToFloat
string--ToInteger|string::ToInteger
string--Upper|string::Upper
transform--Blend|transform::Blend
transform--Build|transform::Build
transform--ClampedLookAtPorthole|transform::ClampedLookAtPorthole
transform--ClampedLookAtWindow|transform::ClampedLookAtWindow
transform--Explode|transform::Explode
transform--LookAt|transform::LookAt
transform--MirrorTransform|transform::MirrorTransform
transform--ProjectOnSphere|transform::ProjectOnSphere
transform--ProjectOnSphericalPorthole|transform::ProjectOnSphericalPorthole
transform--ProjectOnSphericalWindow|transform::ProjectOnSphericalWindow
transform--SmoothRotation|transform::SmoothRotation
uievent--CurViewport|uievent::CurViewport
uievent--Device|uievent::Device
uievent--Drag|uievent::Drag
uievent--MousePosition|uievent::MousePosition
uievent--Ndc|uievent::Ndc
uievent--PrimaryXform|uievent::PrimaryXform
uievent--ScreenRay|uievent::ScreenRay
uievent--XformHandle|uievent::XformHandle
""",
}
