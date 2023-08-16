# Copyright (c) MONAI Consortium
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import copy
import json
import logging
import os
import pprint
import tempfile
from io import StringIO

import ctk
import PyTorchUtils
import qt
import requests
import slicer
import vtk
from MONAIVizLib import ClassUtils, MonaiUtils
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin


class MONAIViz(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)

        self.parent.title = "MONAIViz"
        self.parent.categories = ["MONAI", "Developer Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["MONAI Consortium"]
        self.parent.helpText = """
This extension helps to run chain of MONAI transforms and visualize every stage over an image/label.
See more information in <a href="https://github.com/Project-MONAI/MONAILabel">module documentation</a>.
"""
        self.parent.acknowledgementText = """
Developed by MONAI Consortium
"""

        # Additional initialization step after application startup is complete
        slicer.app.connect("startupCompleted()", self.initializeAfterStartup)

    def initializeAfterStartup(self):
        if not slicer.app.commandOptions().noMainWindow:
            self.settingsPanel = MONAIVizSettingsPanel()
            slicer.app.settingsDialog().addPanel("MONAIViz", self.settingsPanel)


class _ui_MONAIVizSettingsPanel:
    def __init__(self, parent):
        vBoxLayout = qt.QVBoxLayout(parent)

        # settings
        groupBox = ctk.ctkCollapsibleGroupBox()
        groupBox.title = "MONAIViz"
        groupLayout = qt.QFormLayout(groupBox)

        bundleAuthToken = qt.QLineEdit()
        bundleAuthToken.setText("")
        bundleAuthToken.toolTip = "Auth Token for bundles to download from MONAI Model Zoo"
        groupLayout.addRow("Bundle Auth Token:", bundleAuthToken)
        parent.registerProperty(
            "MONAIViz/bundleAuthToken", bundleAuthToken, "text", str(qt.SIGNAL("textChanged(QString)"))
        )

        transformsPath = qt.QLineEdit()
        transformsPath.setText("monai.transforms")
        transformsPath.toolTip = "Transforms Search Path"
        groupLayout.addRow("Transforms Search Path:", transformsPath)
        parent.registerProperty(
            "MONAIViz/transformsPath", transformsPath, "text", str(qt.SIGNAL("textChanged(QString)"))
        )

        fileExtension = qt.QLineEdit()
        fileExtension.setText(".nii.gz")
        fileExtension.toolTip = "Default extension for uploading images/labels"
        groupLayout.addRow("File Extension:", fileExtension)
        parent.registerProperty("MONAIViz/fileExtension", fileExtension, "text", str(qt.SIGNAL("textChanged(QString)")))

        imageKey = qt.QLineEdit()
        imageKey.setText("image")
        imageKey.toolTip = "Image Key in Dictionary"
        groupLayout.addRow("Image Key:", imageKey)
        parent.registerProperty("MONAIViz/imageKey", imageKey, "text", str(qt.SIGNAL("textChanged(QString)")))

        labelKey = qt.QLineEdit()
        labelKey.setText("label")
        labelKey.toolTip = "Label Key in Dictionary"
        groupLayout.addRow("Label Key:", labelKey)
        parent.registerProperty("MONAIViz/labelKey", labelKey, "text", str(qt.SIGNAL("textChanged(QString)")))

        bufferArgs = qt.QLineEdit()
        bufferArgs.setInputMask("00")
        bufferArgs.setText("15")
        bufferArgs.toolTip = "Buffer/Extra Args for each Transform while adding/editing"
        groupLayout.addRow("Buffer Args:", bufferArgs)
        parent.registerProperty("MONAIViz/bufferArgs", bufferArgs, "text", str(qt.SIGNAL("textChanged(QString)")))

        vBoxLayout.addWidget(groupBox)
        vBoxLayout.addStretch(1)


class MONAIVizSettingsPanel(ctk.ctkSettingsPanel):
    def __init__(self, *args, **kwargs):
        ctk.ctkSettingsPanel.__init__(self, *args, **kwargs)
        self.ui = _ui_MONAIVizSettingsPanel(self)


class MONAIVizWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None):
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)  # needed for parameter node observation
        self.logic = None
        self._parameterNode = None
        self._updatingGUIFromParameterNode = False
        self.transforms = None
        self.tmpdir = slicer.util.tempDirectory("slicer-monai-viz", includeDateTime=False)
        print(f"Using Temp Directory: {self.tmpdir}")

        self.ctx = TransformCtx()

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/MONAIViz.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = MONAIVizLogic()

        # Connections
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.ui.addTransformButton.connect("clicked(bool)", self.onAddTransform)
        self.ui.editTransformButton.connect("clicked(bool)", self.onEditTransform)
        self.ui.removeTransformButton.connect("clicked(bool)", self.onRemoveTransform)
        self.ui.moveUpButton.connect("clicked(bool)", self.onMoveUpTransform)
        self.ui.moveDownButton.connect("clicked(bool)", self.onMoveDownTransform)
        self.ui.loadTransformButton.connect("clicked(bool)", self.onLoadTransform)
        self.ui.saveTransformButton.connect("clicked(bool)", self.onSaveTransform)
        self.ui.modulesComboBox.connect("currentIndexChanged(int)", self.onSelectModule)
        self.ui.transformTable.connect("cellClicked(int, int)", self.onSelectTransform)
        self.ui.transformTable.connect("cellDoubleClicked(int, int)", self.onEditTransform)
        self.ui.importBundleButton.connect("clicked(bool)", self.onImportBundle)
        self.ui.runTransformButton.connect("clicked(bool)", self.onRunTransform)
        self.ui.clearTransformButton.connect("clicked(bool)", self.onClearTransform)
        self.ui.previewTransformButton.connect("clicked(bool)", self.onShowDictionary)

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()

        self.ui.importBundleButton.setIcon(self.icon("download.png"))
        self.ui.addTransformButton.setIcon(self.icon("icons8-insert-row-48.png"))
        self.ui.removeTransformButton.setIcon(self.icon("icons8-delete-row-48.png"))
        self.ui.editTransformButton.setIcon(self.icon("icons8-edit-row-48.png"))
        self.ui.runTransformButton.setIcon(self.icon("icons8-red-circle-48.png"))
        self.ui.previewTransformButton.setIcon(self.icon("icons8-preview-48.png"))
        self.ui.clearTransformButton.setIcon(self.icon("icons8-delete-document-48.png"))
        self.ui.loadTransformButton.setIcon(self.icon("icons8-load-48.png"))
        self.ui.saveTransformButton.setIcon(self.icon("icons8-save-48.png"))

        headers = ["Active", "Status", "Target", "Args"]
        self.ui.transformTable.setColumnCount(len(headers))
        self.ui.transformTable.setHorizontalHeaderLabels(headers)
        self.ui.transformTable.setColumnWidth(0, 40)
        self.ui.transformTable.setColumnWidth(1, 60)
        self.ui.transformTable.setColumnWidth(2, 160)
        self.ui.transformTable.setEditTriggers(qt.QTableWidget.NoEditTriggers)
        self.ui.transformTable.setSelectionBehavior(qt.QTableView.SelectRows)

        # self.ui.imagePathLineEdit.setCurrentPath("C:/Dataset/Radiology/Task09_Spleen/imagesTr/spleen_2.nii.gz")
        # self.ui.labelPathLineEdit.setCurrentPath("C:/Dataset/Radiology/Task09_Spleen/labelsTr/spleen_2.nii.gz")
        self.ui.textEdit.setText("{}")

        self.refreshVersion()

    def cleanup(self):
        self.removeObservers()

    def enter(self):
        self.initializeParameterNode()

    def exit(self):
        self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    def onSceneStartClose(self, caller, event):
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event):
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self):
        self.setParameterNode(self.logic.getParameterNode())

        # Select default input nodes if nothing is selected yet to save a few clicks for the user
        if not self._parameterNode.GetNodeReference("InputVolume"):
            firstVolumeNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode")
            if firstVolumeNode:
                self._parameterNode.SetNodeReferenceID("InputVolume", firstVolumeNode.GetID())

    def setParameterNode(self, inputParameterNode):
        if inputParameterNode:
            self.logic.setDefaultParameters(inputParameterNode)

        # Unobserve previously selected parameter node and add an observer to the newly selected.
        # Changes of parameter node are observed so that whenever parameters are changed by a script or any other module
        # those are reflected immediately in the GUI.
        if self._parameterNode is not None:
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        self._parameterNode = inputParameterNode
        if self._parameterNode is not None:
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

        # Initial GUI update
        self.updateGUIFromParameterNode()

    def updateGUIFromParameterNode(self, caller=None, event=None):
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return

        # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
        self._updatingGUIFromParameterNode = True

        # All the GUI updates are done
        self._updatingGUIFromParameterNode = False

    def updateParameterNodeFromGUI(self, caller=None, event=None):
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return

        wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

        # self._parameterNode.SetParameter("Threshold", str(self.ui.imageThresholdSliderWidget.value))

        self._parameterNode.EndModify(wasModified)

    def icon(self, name="MONAILabel.png"):
        # It should not be necessary to modify this method
        iconPath = os.path.join(os.path.dirname(__file__), "Resources", "Icons", name)
        if os.path.exists(iconPath):
            return qt.QIcon(iconPath)
        return qt.QIcon()

    def refreshVersion(self):
        print("Refreshing Version...")

        self.ui.monaiVersionComboBox.clear()
        monai = self.logic.importMONAI()
        version = monai.__version__

        self.ui.monaiVersionComboBox.addItem(version)
        self.ui.monaiVersionComboBox.setCurrentText(version)

        self.refreshTransforms()

        # bundle names
        auth_token = slicer.util.settingsValue("MONAIViz/bundleAuthToken", "")
        auth_token = auth_token if auth_token else None
        bundles = MonaiUtils.list_bundles(auth_token=auth_token)

        self.ui.bundlesComboBox.clear()
        self.ui.bundlesComboBox.addItems(list(sorted({b[0] for b in bundles})))
        idx = max(0, self.ui.bundlesComboBox.findText("spleen_ct_segmentation"))
        self.ui.bundlesComboBox.setCurrentIndex(idx)

        self.ui.bundleStageComboBox.clear()
        self.ui.bundleStageComboBox.addItems(["pre"])

    def refreshTransforms(self):
        if not self.ui.monaiVersionComboBox.currentText:
            return

        module = slicer.util.settingsValue("MONAIViz/transformsPath", "monai.transforms")
        print(f"Refreshing Transforms for module: {module}")
        self.transforms = MonaiUtils.list_transforms(module)

        self.ui.modulesComboBox.clear()
        self.ui.modulesComboBox.addItem("monai.transforms")
        self.ui.modulesComboBox.addItems(sorted(list({v["module"] for v in self.transforms.values()})))

        idx = max(0, self.ui.modulesComboBox.findText("monai.transforms.io.dictionary"))
        self.ui.modulesComboBox.setCurrentIndex(idx)
        # self.onSelectModule(self.ui.modulesComboBox.currentText)

    def onImportBundle(self):
        if not self.ui.monaiVersionComboBox.currentText:
            return

        name = self.ui.bundlesComboBox.currentText
        bundle_dir = os.path.join(self.tmpdir, "bundle")
        this_bundle = os.path.join(bundle_dir, name)
        if not os.path.exists(this_bundle):
            if not slicer.util.confirmOkCancelDisplay(
                f"This will download bundle: {name} from MONAI ZOO.\n\nAre you sure to continue?"
            ):
                return

            try:
                qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)

                print(f"Downloading {name} to {bundle_dir}")
                auth_token = slicer.util.settingsValue("MONAIViz/bundleAuthToken", "")
                auth_token = auth_token if auth_token else None
                MonaiUtils.download_bundle(name, bundle_dir, auth_token=auth_token)
            finally:
                qt.QApplication.restoreOverrideCursor()

        transforms = MonaiUtils.transforms_from_bundle(name, bundle_dir)

        table = self.ui.transformTable
        table.clearContents()
        table.setRowCount(len(transforms))

        # Temporary:: clear current scene
        slicer.mrmlScene.Clear(0)

        for pos, t in enumerate(transforms):
            name = t["_target_"]
            args = copy.copy(t)
            args.pop("_target_")

            print(f"Importing Transform: {name} => {args}")
            # table.setCellWidget(pos, 0, EditButtonsWidget())

            box = qt.QCheckBox()
            box.setChecked(True)
            box.setProperty("row", pos)
            widget = qt.QWidget()
            box.connect("clicked(bool)", lambda checked: self.onBoxClicked(checked, box.row))
            layout = qt.QHBoxLayout(widget)
            layout.addWidget(box)
            layout.setAlignment(qt.Qt.AlignCenter)
            layout.setContentsMargins(0, 0, 0, 0)
            widget.setLayout(layout)

            table.setCellWidget(pos, 0, widget)

            item = qt.QTableWidgetItem()
            item.setIcon(self.icon("icons8-yellow-circle-48.png"))
            table.setItem(pos, 1, item)

            table.setItem(pos, 2, qt.QTableWidgetItem(name))
            table.setItem(pos, 3, qt.QTableWidgetItem(ClassUtils.args_to_expression(args)))

    def onSelectModule(self):
        module = self.ui.modulesComboBox.currentText
        print(f"Selected Module: {module}")

        filtered = [k for k, v in self.transforms.items() if module == "monai.transforms" or v["module"] == module]
        filtered = sorted([f.split(".")[-1] for f in filtered])
        self.ui.transformsComboBox.clear()
        self.ui.transformsComboBox.addItems(filtered)

    def onBoxClicked(self, clicked, current_row):
        next_idx = current_row
        next_exp = self.get_exp(next_idx)
        self.ctx.set_next(next_idx, next_exp)
        self.ctx.reset()

    def onSelectTransform(self, row, col):
        selected = True if row >= 0 and self.ui.transformTable.rowCount else False
        self.ui.editTransformButton.setEnabled(selected)
        self.ui.removeTransformButton.setEnabled(selected)
        self.ui.moveUpButton.setEnabled(selected and row > 0)
        self.ui.moveDownButton.setEnabled(selected and row < self.ui.transformTable.rowCount - 1)
        self.ui.runTransformButton.setEnabled(selected)
        self.ui.clearTransformButton.setEnabled(self.ctx.valid())
        self.ui.saveTransformButton.setEnabled(selected)

    def onEditTransform(self, row=-1, col=-1):
        print(f"Selected Transform for Edit: {row}")
        row = self.ui.transformTable.currentRow() if row < 0 else row
        if row < 0:
            return

        name = str(self.ui.transformTable.item(row, 2).text())
        exp = str(self.ui.transformTable.item(row, 3).text())

        doc_html = os.path.join(self.tmpdir, "transforms.html")
        doc_url = f"https://docs.monai.io/en/{self.ui.monaiVersionComboBox.currentText}/transforms.html"
        if not os.path.exists(doc_html):
            with open(doc_html, "wb", encoding="utf-8") as fp:
                fp.write(requests.get(doc_url).content)

        with open(doc_html, encoding="utf-8") as fp:
            contents = fp.readlines()

        doc_section = tempfile.NamedTemporaryFile(suffix=".html").name
        short_name = name.split(".")[-1].lower()

        sb = (f'<section id="{short_name}">', f"<section id='{short_name}'>")
        sc = -1
        found = False
        with open(doc_section, "w", encoding="utf-8") as fp:
            for c in contents:
                c = c.rstrip()
                if c in sb:
                    sc = 1
                elif sc > 0:
                    if c.startswith("<section"):
                        sc += 1
                    elif c.startswith("</section>"):
                        sc -= 1

                if sc > 0:
                    c = c.replace('<span class="viewcode-link"><span class="pre">[source]</span></span>', "")
                    c = c.replace("#</a>", "</a>")
                    c = c.replace('href="', 'href="' + doc_url)
                    fp.write(c)
                    fp.write(os.linesep)
                    found = True
                if sc == 0:
                    fp.write(c)
                    fp.write(os.linesep)
                    break

            if not found:
                fp.write(f'<p>Visit <a href="{doc_url}">MONAI Docs</a> for more information</p>')

        buffer_rows = int(slicer.util.settingsValue("MONAIViz/bufferArgs", "15"))
        dlg = CustomDialog(self.resourcePath, name, ClassUtils.expression_to_args(exp), doc_section, buffer_rows)
        dlg.exec()
        os.unlink(doc_section)

        if dlg.updatedArgs is not None:
            new_exp = ClassUtils.args_to_expression(dlg.updatedArgs)
            print(f"Old:: {exp}")
            print(f"New:: {new_exp}")
            if exp != new_exp:
                if row < self.ctx.next_idx or row == self.ui.transformTable.rowCount - 1:
                    self.onClearTransform()
                self.ui.transformTable.item(row, 3).setText(new_exp)
                print("Updated for new args...")

    def onAddTransform(self):
        print(f"Adding Transform: {self.ui.modulesComboBox.currentText}.{self.ui.transformsComboBox.currentText}")
        if not self.ui.modulesComboBox.currentText or not self.ui.transformsComboBox.currentText:
            return

        t = self.ui.transformsComboBox.currentText
        m = self.ui.modulesComboBox.currentText

        v = ""
        if t[-1] == "d":  # this is a dictionary transform
            # now exclude some transforms whose name happens to end with d
            if t not in ["AffineGrid", "Decollated", "RandAffineGrid", "RandDeformGrid"]:
                image_key = slicer.util.settingsValue("SlicerMONAIViz/imageKey", "image")
                label_key = slicer.util.settingsValue("SlicerMONAIViz/labelKey", "label")
                v = f"keys=['{image_key}', '{label_key}']"

        self.addTransform(-1, None, t, v)

    def addTransform(self, pos, m, t, v, active=True):
        table = self.ui.transformTable
        pos = pos if pos >= 0 else table.rowCount if table.currentRow() < 0 else table.currentRow() + 1

        table.insertRow(pos)
        # table.setCellWidget(pos, 0, EditButtonsWidget())

        box = qt.QCheckBox()
        box.setChecked(active)
        box.setProperty("row", pos)
        widget = qt.QWidget()
        box.connect("clicked(bool)", lambda checked: self.onBoxClicked(checked, box.row))
        layout = qt.QHBoxLayout(widget)
        layout.addWidget(box)
        layout.setAlignment(qt.Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        widget.setLayout(layout)

        table.setCellWidget(pos, 0, widget)

        item = qt.QTableWidgetItem()
        item.setIcon(self.icon("icons8-yellow-circle-48.png"))
        table.setItem(pos, 1, item)

        table.setItem(pos, 2, qt.QTableWidgetItem(f"{m}.{t}" if m else t))
        table.setItem(pos, 3, qt.QTableWidgetItem(v if v else ""))

        table.selectRow(pos)
        self.onSelectTransform(pos, 0)

    def onRemoveTransform(self):
        row = self.ui.transformTable.currentRow()
        if row < 0:
            return
        self.ui.transformTable.removeRow(row)
        self.onSelectTransform(-1, -1)

    def onMoveUpTransform(self):
        row = self.ui.transformTable.currentRow()
        if row < 0:
            return

        t = str(self.ui.transformTable.item(row, 2).text())
        v = str(self.ui.transformTable.item(row, 3).text())
        active = self.ui.transformTable.cellWidget(row, 0).findChild("QCheckBox").isChecked()
        self.onRemoveTransform()
        self.addTransform(row - 1, None, t, v, active)

    def onMoveDownTransform(self):
        row = self.ui.transformTable.currentRow()
        if row < 0:
            return

        t = str(self.ui.transformTable.item(row, 2).text())
        v = str(self.ui.transformTable.item(row, 3).text())
        active = self.ui.transformTable.cellWidget(row, 0).findChild("QCheckBox").isChecked()
        self.onRemoveTransform()
        self.addTransform(row + 1, None, t, v, active)

    def prepare_dict(self):
        image = self.ui.imagePathLineEdit.currentPath
        label = self.ui.labelPathLineEdit.currentPath
        additional = json.loads(self.ui.textEdit.toPlainText())

        image_key = slicer.util.settingsValue("MONAIViz/imageKey", "image")
        label_key = slicer.util.settingsValue("MONAIViz/labelKey", "label")

        d = {image_key: image, **additional}
        if label:
            d[label_key] = label
        return d

    def get_exp(self, row):
        name = str(self.ui.transformTable.item(row, 2).text())
        args = str(self.ui.transformTable.item(row, 3).text())
        return f"monai.transforms.{name}({args})"

    def onRunTransform(self):
        if not self.ui.imagePathLineEdit.currentPath:
            slicer.util.errorDisplay("Image is not selected!")
            return

        current_row = self.ui.transformTable.currentRow()
        print(f"Current Row: {current_row}; Total: {self.ui.transformTable.rowCount}")
        if current_row < 0:
            return

        image_key = slicer.util.settingsValue("MONAIViz/imageKey", "image")
        label_key = slicer.util.settingsValue("MONAIViz/labelKey", "label")

        try:
            qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
            # Temporary:: clear current scene
            slicer.mrmlScene.Clear(0)

            current_exp = self.get_exp(current_row)
            d = self.ctx.get_d(current_exp, d=self.prepare_dict())

            import monai

            print(monai.__version__)

            if self.ctx.last_exp != current_exp:
                for row in range(self.ctx.next_idx, current_row + 1):
                    if self.ui.transformTable.cellWidget(row, 0).findChild("QCheckBox").isChecked():
                        exp = self.get_exp(row)
                        print("")
                        print("====================================================================")
                        print(f"Run:: {exp}")
                        print("====================================================================")

                        t = eval(exp)
                        if isinstance(d, list):
                            d = [t(dx) for dx in d]  # Batched Transforms
                        else:
                            d = t(d)

                        self.ctx.set_d(d, exp, key=image_key)
                        self.ui.transformTable.item(row, 1).setIcon(self.icon("icons8-green-circle-48.png"))
                    else:
                        self.ui.transformTable.item(row, 1).setIcon(self.icon("icons8-yellow-circle-48.png"))
                        continue

            next_idx = current_row
            next_exp = self.get_exp(next_idx)
            if current_row + 1 < self.ui.transformTable.rowCount:
                next_idx = current_row + 1
                next_exp = self.get_exp(next_idx)

                self.ui.transformTable.selectRow(next_idx)
                for row in range(next_idx, self.ui.transformTable.rowCount):
                    self.ui.transformTable.item(row, 1).setIcon(self.icon("icons8-yellow-circle-48.png"))

            v = self.ctx.get_tensor(key=image_key)
            volumeNode = slicer.util.addVolumeFromArray(v)

            origin, spacing, direction = self.ctx.get_tensor_osd(key=image_key)
            volumeNode.SetName(os.path.basename(self.ui.imagePathLineEdit.currentPath))
            volumeNode.SetOrigin(origin)
            volumeNode.SetSpacing(spacing)
            volumeNode.SetIJKToRASDirections(direction)
            # logging.info(f"Volume direction: {direction}")

            l = self.ctx.get_tensor(key=label_key)
            labelNode = None
            if l is not None:
                labelNode = slicer.util.addVolumeFromArray(l, nodeClassName="vtkMRMLLabelMapVolumeNode")
                origin, spacing, direction = self.ctx.get_tensor_osd(key=label_key)
                labelNode.SetName(os.path.basename(self.ui.labelPathLineEdit.currentPath))
                labelNode.SetOrigin(origin)
                labelNode.SetSpacing(spacing)
                labelNode.SetIJKToRASDirections(direction)
                # logging.info(f"Label direction: {direction}")
            slicer.util.setSliceViewerLayers(volumeNode, label=labelNode, fit=True)

            self.ctx.set_next(next_idx, next_exp)
            self.ui.clearTransformButton.setEnabled(self.ctx.valid())
        finally:
            qt.QApplication.restoreOverrideCursor()

    def onClearTransform(self):
        self.ctx.reset()
        for row in range(0, self.ui.transformTable.rowCount):
            self.ui.transformTable.item(row, 1).setIcon(self.icon("icons8-yellow-circle-48.png"))
        self.ui.clearTransformButton.setEnabled(self.ctx.valid())

    def onLoadTransform(self):
        fname = qt.QFileDialog().getOpenFileName(None, "Select json file to import", "", "(*.json)")
        if fname:
            with open(fname) as transformFile:
                transforms = json.load(transformFile)

            for idx, transform in transforms.items():
                t = transform["name"]
                v = ""

                if t[-1] == "d":  # this is a dictionary transform
                    # now exclude some transforms whose name happens to end with d
                    if t not in ["AffineGrid", "Decollated", "RandAffineGrid", "RandDeformGrid"]:
                        v = transform["args"]

                self.addTransform(int(idx), None, t, v)

    def onSaveTransform(self):
        fname = qt.QFileDialog().getSaveFileName(None, "Save file", "", "json (*.json)")
        if fname:
            rows = self.ui.transformTable.rowCount
            table = {}
            for row in range(rows):
                name = str(self.ui.transformTable.item(row, 2).text())
                args = str(self.ui.transformTable.item(row, 3).text())
                table[row] = {"name": name, "args": args}

            with open(fname, "w") as output:
                json.dump(table, output)

    def onShowDictionary(self):
        dlg = TransformDictDialog(self.ctx.get_d(None, d=self.prepare_dict()), self.resourcePath)
        dlg.exec()


class EditButtonsWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = qt.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        b1 = qt.QPushButton("")
        b1.setIcon(self.icon("icons8-green-circle-16.png"))
        b1.setMaximumWidth(20)
        layout.addWidget(b1)

        b2 = qt.QPushButton("")
        b2.setIcon(self.icon("icons8-preview-16.png"))
        b2.setMaximumWidth(20)
        layout.addWidget(b2)

        b3 = qt.QPushButton("")
        b3.setIcon(self.icon("icons8-delete-document-16.png"))
        b3.setMaximumWidth(20)
        layout.addWidget(b3)

        self.setLayout(layout)

    def icon(self, name):
        # It should not be necessary to modify this method
        iconPath = os.path.join(os.path.dirname(__file__), "Resources", "Icons", name)
        if os.path.exists(iconPath):
            return qt.QIcon(iconPath)
        return qt.QIcon()


class CustomDialog(qt.QDialog):
    def __init__(self, resourcePath, name, args, doc_html, buffer_rows):
        super().__init__()
        self.name = name
        self.args = args
        self.updatedArgs = None
        self.buffer_rows = buffer_rows

        short_name = name.split(".")[-1]
        self.setWindowTitle(f"Edit - {short_name}")
        print(f"{name} => {args}")

        layout = qt.QVBoxLayout()
        uiWidget = slicer.util.loadUI(resourcePath("UI/MONAITransformDialog.ui"))
        layout.addWidget(uiWidget)

        self.ui = slicer.util.childWidgetVariables(uiWidget)
        self.setLayout(layout)

        url = f"https://docs.monai.io/en/stable/transforms.html#{short_name.lower()}"
        self.ui.nameLabel.setText('<a href="' + url + '">' + short_name + "</a>")

        headers = ["Name", "Value"]
        table = self.ui.tableWidget
        table.setRowCount(len(args) + buffer_rows)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setColumnWidth(0, 150)
        table.setColumnWidth(1, 200)

        for row, (k, v) in enumerate(args.items()):
            table.setItem(row, 0, qt.QTableWidgetItem(k))
            table.setItem(row, 1, qt.QTableWidgetItem(str(v)))

        self.ui.updateButton.connect("clicked(bool)", self.onUpdate)
        self.ui.webEngineView.url = qt.QUrl.fromLocalFile(doc_html)

    def onUpdate(self):
        args = {}
        table = self.ui.tableWidget
        for row in range(table.rowCount):
            k = table.item(row, 0)
            k = str(k.text()) if k else None
            v = table.item(row, 1)
            v = str(v.text()) if v else None
            if k:
                print(f"Row: {row} => {k} => {v}")
                try:
                    v = eval(v) if v else v
                except:
                    pass
                args[k] = v

        self.updatedArgs = args
        self.close()


class TransformDictDialog(qt.QDialog):
    def __init__(self, data, resourcePath):
        super().__init__()

        self.setWindowTitle("Dictionary Data")
        print(f"{data.keys()}")

        layout = qt.QVBoxLayout()
        uiWidget = slicer.util.loadUI(resourcePath("UI/MONAIDictionaryDialog.ui"))
        layout.addWidget(uiWidget)

        self.ui = slicer.util.childWidgetVariables(uiWidget)
        self.setLayout(layout)

        s = StringIO()
        pprint.pprint(data, s, indent=2)
        self.ui.dataTextEdit.setPlainText(s.getvalue())

        headers = ["Key", "Type", "Shape", "Value"]
        tree = self.ui.treeWidget
        tree.setColumnCount(len(headers))
        tree.setHeaderLabels(headers)
        tree.setColumnWidth(0, 150)
        tree.setColumnWidth(1, 75)
        tree.setColumnWidth(2, 100)

        def get_val(v):
            if type(v) in (int, float, bool, str):
                return str(v)

            s = StringIO()
            pprint.pprint(v, s, compact=True, indent=1, width=-1)
            return s.getvalue().replace("\n", "")

        items = []
        for key, val in data.items():
            if isinstance(val, dict):
                item = qt.QTreeWidgetItem([key])
                for k1, v1 in val.items():
                    tvals = [k1, type(v1).__name__, v1.shape if hasattr(v1, "shape") else "", get_val(v1)]
                    child = qt.QTreeWidgetItem(tvals)
                    item.addChild(child)
            else:
                tvals = [key, type(val).__name__, val.shape if hasattr(val, "shape") else "", get_val(val)]
                item = qt.QTreeWidgetItem(tvals)
            items.append(item)

        tree.insertTopLevelItems(0, items)


class MONAIVizLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.torchLogic = PyTorchUtils.PyTorchUtilsLogic()

    def setDefaultParameters(self, parameterNode):
        # if not parameterNode.GetParameter("Threshold"):
        #     parameterNode.SetParameter("Threshold", "100.0")
        pass

    def process(self):
        import time

        startTime = time.time()
        logging.info("Processing started")

        stopTime = time.time()
        logging.info(f"Processing completed in {stopTime - startTime:.2f} seconds")

    def importMONAI(self):
        if not self.torchLogic.torchInstalled():
            logging.info("PyTorch module not found")
            torch = self.torchLogic.installTorch(askConfirmation=True)
            if torch is None:
                slicer.util.errorDisplay(
                    "PyTorch needs to be installed to use the MONAI extension."
                    " Please reload this module to install PyTorch."
                )
                return None
        try:
            import monai
        except ModuleNotFoundError:
            with self.showWaitCursor(), self.peakPythonConsole():
                monai = self.installMONAI()
        logging.info(f"MONAI {monai.__version__} imported correctly")
        return monai

    @staticmethod
    def installMONAI(confirm=True):
        if confirm and not slicer.app.commandOptions().testingEnabled:
            install = slicer.util.confirmOkCancelDisplay(
                "MONAI will be downloaded and installed now. The process might take some minutes."
            )
            if not install:
                logging.info("Installation of MONAI aborted by user")
                return None
        slicer.util.pip_install("monai[itk,nibabel,tqdm]")
        import monai

        logging.info(f"MONAI {monai.__version__} installed correctly")
        return monai


class MONAIVizTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_MONAIViz1()

    def test_MONAIViz1(self):
        self.delayDisplay("Starting the test")
        self.delayDisplay("Test passed")


class TransformCtx:
    def __init__(self):
        self.d = None
        self.last_exp = ""
        self.next_idx = 0
        self.next_exp = ""
        self.channel = False
        self.bidx = 0
        self.original_spatial_shape = None
        self.original_affine = None

    def reset(self):
        self.__init__()

    def valid(self) -> bool:
        return False if self.d is None or self.next_idx == 0 else True

    def valid_for_next(self, exp) -> bool:
        return True if exp and self.next_exp and exp == self.next_exp else False

    def get_d(self, exp, d=None):
        if exp is None:
            if self.valid():
                bidx = self.bidx % len(self.d) if isinstance(self.d, list) else -1
                return self.d[bidx] if bidx >= 0 else self.d
            return d

        if not self.valid_for_next(exp):
            self.reset()

        if not self.valid():
            print(d)
            return d
        return self.d

    def set_d(self, d, exp, key):
        key_tensor = d[self.bidx % len(d)][key] if isinstance(d, list) else d[key]
        print(f"{key}: {key_tensor.shape}")

        if self.original_spatial_shape is None:
            self.original_spatial_shape = key_tensor.shape
            self.original_affine = key_tensor.affine.numpy()

        if "EnsureChannelFirstd" in exp:
            self.channel = True

        self.d = d
        self.last_exp = exp

    def set_next(self, next_idx, next_exp):
        if self.next_idx == next_idx and self.next_exp == next_exp:
            self.bidx += 1
        else:
            self.next_idx = next_idx
            self.next_exp = next_exp

    def get_tensor(self, key, transpose=True):
        import numpy as np
        import torch

        bidx = self.bidx % len(self.d) if isinstance(self.d, list) else -1
        d = self.d[bidx] if bidx >= 0 else self.d
        if d.get(key) is None:
            return None

        key_tensor = d[key]
        if isinstance(key_tensor, str) or key_tensor is None:
            return None

        v = key_tensor.numpy() if isinstance(key_tensor, torch.Tensor) else key_tensor
        v = np.squeeze(v, axis=0) if self.channel else v
        v = v.transpose() if transpose else v

        print(f"Display {key}{'[' + str(bidx) + ']' if bidx >= 0 else ''}: {v.shape}")
        return v

    def get_tensor_osd(self, key, scale=False):
        import numpy as np
        from monai.transforms.utils import scale_affine

        bidx = self.bidx % len(self.d) if isinstance(self.d, list) else -1
        d = self.d[bidx] if bidx >= 0 else self.d
        if d.get(key) is None:
            return None

        key_tensor = d[key]
        actual_shape = key_tensor.shape[1:] if self.channel else key_tensor.shape

        affine = (
            scale_affine(self.original_affine, self.original_spatial_shape, actual_shape)
            if scale
            else key_tensor.affine.numpy()
        )

        # convert_aff_mat = np.diag([-1, -1, 1, 1])  # RAS <-> LPS conversion matrix
        # affine = convert_aff_mat @ affine  # convert from RAS to LPS

        dim = affine.shape[0] - 1
        _origin_key = (slice(-1), -1)
        _m_key = (slice(-1), slice(-1))

        origin = affine[_origin_key]
        spacing = np.linalg.norm(affine[_m_key] @ np.eye(dim), axis=0)
        direction = affine[_m_key] @ np.diag(1 / spacing)

        return origin, spacing, direction
