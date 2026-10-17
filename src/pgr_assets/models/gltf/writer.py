import pygltflib as gl

from pgr_assets.models.format import to_plain
from pgr_assets.models.gltf.buffer import Blob
from pgr_assets.models.gltf.document import Document
from pgr_assets.models.gltf.extras import emit_scene_extras
from pgr_assets.models.gltf.materials import WEBP_EXTENSION, Shading
from pgr_assets.models.gltf.meshes import Meshes
from pgr_assets.models.gltf.nodes import emit_nodes
from pgr_assets.models.scene import Scene, find_cleared_nodes


def build_gltf(scene: Scene) -> gl.GLTF2:
    blob = Blob()
    shading = Shading(blob, scene.textures)
    nodes = emit_nodes(scene, shading)

    meshes = Meshes(blob, shading, find_cleared_nodes(scene.nodes, scene.parts))
    for part in scene.parts:
        meshes.add(part, nodes[part.node])
    meshes.finish()

    roots = [i for i, node in enumerate(scene.nodes) if node.parent is None]
    root_scene = gl.Scene(nodes=roots, extras=to_plain(emit_scene_extras(scene, shading)))
    document = Document(
        asset=gl.Asset(generator="pgr-assets"),
        scene=0,
        scenes=[root_scene],
        nodes=nodes,
        meshes=meshes.meshes,
        skins=meshes.skins,
        materials=shading.materials,
        textures=shading.textures,
        images=shading.images,
        samplers=shading.samplers,
        accessors=blob.accessors,
        bufferViews=blob.views,
        buffers=[gl.Buffer(byteLength=len(blob.data))],
    )
    if shading.images:
        document.extensionsUsed.append(WEBP_EXTENSION)
        document.extensionsRequired = [WEBP_EXTENSION]
    document.set_binary_blob(bytes(blob.data))
    return document
