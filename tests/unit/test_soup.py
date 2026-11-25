"""Model soup: adapter tensors map to the base weight they change; factors are never averaged."""
from dev.soup import lora_delta_keys


def test_lora_keys_map_to_base_weights():
    keys = ['base_model.model.model.layers.0.mlp.down_proj.lora_A.weight',
            'base_model.model.model.layers.0.mlp.down_proj.lora_B.weight']
    assert lora_delta_keys(keys) == {'model.layers.0.mlp.down_proj.weight': tuple(keys)}
    assert lora_delta_keys(keys[1:]) == {}
