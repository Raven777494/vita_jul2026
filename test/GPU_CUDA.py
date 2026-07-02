from llama_cpp import Llama
model_path=r"D:\Desktop\engine7b\models\Mistral-Nemo-Instruct-2407-Q5_K_M.gguf"
model = Llama(model_path=model_path, gpu_layers=-1)