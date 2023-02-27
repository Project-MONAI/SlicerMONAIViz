cmake_minimum_required(VERSION 3.16.3...3.19.7 FATAL_ERROR)

project(MONAIViz)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/Project-MONAI/SlicerMONAIViz#slicermonaiviz")
set(EXTENSION_CATEGORY "Developer Tools")
set(EXTENSION_CONTRIBUTORS "MONAI Consortium")
set(EXTENSION_DESCRIPTION "This extension helps to run chain of MONAI transforms and visualize every stage over an image/label. See more information in <a href=\"https://github.com/Project-MONAI/MONAILabel\">MONAILabel documentation</a>.")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/Project-MONAI/SlicerMONAIViz/main/MONAIViz/Resources/Icons/MONAIViz.png")
set(EXTENSION_SCREENSHOTURLS "https://github.com/Project-MONAI/SlicerMONAIViz/raw/main/Screenshots/1.jpg https://github.com/Project-MONAI/SlicerMONAIViz/raw/main/Screenshots/2.jpg https://github.com/Project-MONAI/SlicerMONAIViz/raw/main/Screenshots/3.jpg https://github.com/Project-MONAI/SlicerMONAIViz/raw/main/Screenshots/4.jpg")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(MONAIViz)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
