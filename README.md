# SlicerMONAIViz

## MONAI Developer Plugin for 3D Slicer

SlicerMONAIViz currently supports:
- import pre-processing definitions for available bundles from MONAI model zoo
- add/remove/re-order any MONAI transform to the list of transforms
- apply a sequence of transforms step-by-step over input image/label
- visualize image/label outputs for every transform run
- check the data/dictionary stats for every transform run

<hr/>

![image](Screenshots/1.jpg)

<hr/>

## Installing Plugin

### Prerequisites
You need to install MONAI and dependencies before using this plugin.

- Open Python Console (View Menu) in 3D Slicer
- Running following commands
  - `pip_install('monai')`
  - `pip_install('nibabel')`
- Restart 3D Slicer

### Install Plugin in Developer Mode

- `git clone git@github.com:Project-MONAI/SlicerMONAIViz.git`
- Open 3D Slicer: Go to **Edit** -> **Application Settings** -> **Modules** -> **Additional Module Paths**
- Add New Module Path: _<FULL_PATH>_/SlicerMONAIViz
- _**Restart**_ 3D Slicer
