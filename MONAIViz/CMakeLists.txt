#-----------------------------------------------------------------------------
set(MODULE_NAME MONAIViz)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  ${MODULE_NAME}Lib/__init__.py
  ${MODULE_NAME}Lib/utils.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/Icons/refresh-icon.png
  Resources/Icons/upload.svg
  Resources/Icons/icons8-insert-row-48.png
  Resources/Icons/icons8-preview-48.png
  Resources/Icons/icons8-red-circle-48.png
  Resources/Icons/icons8-yellow-circle-48.png
  Resources/Icons/icons8-delete-document-48.png
  Resources/Icons/icons8-delete-row-48.png
  Resources/Icons/icons8-edit-row-48.png
  Resources/Icons/icons8-green-circle-48.png
  Resources/Icons/done.png
  Resources/Icons/download.png
  Resources/Icons/MONAI.png
  Resources/UI/${MODULE_NAME}.ui
  Resources/UI/MONAITransformDialog.ui
  Resources/UI/MONAIDictionaryDialog.ui 
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )

#-----------------------------------------------------------------------------
if(BUILD_TESTING)

  # Register the unittest subclass in the main script as a ctest.
  # Note that the test will also be available at runtime.
  slicer_add_python_unittest(SCRIPT ${MODULE_NAME}.py)

  # Additional build-time testing
  add_subdirectory(Testing)
endif()
