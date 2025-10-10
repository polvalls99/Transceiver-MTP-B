import os
import sys
import time
from collections import deque

# =============================================================================
# PARTE 1: OBJETOS SIMULADOS (MOCKS)
# Estas clases falsas imitan el comportamiento de las librerías de hardware.
# =============================================================================

class MockPi:
    """A mock pigpio.pi class to simulate the connection."""
    def __init__(self, hostname, port):
        self.hostname = hostname
        self.port = port
        self._connected = True

    @property
    def connected(self):
        return self._connected

    def stop(self):
        self._connected = False
        print("[MockPi] Connection stopped.")

class MockNRF24:
    """A mock NRF24 class to simulate the radio module."""
    
    # The "airwaves" queue is shared between all instances to simulate radio space.
    _airwaves = deque()

    def __init__(self, pi, ce, payload_size, **kwargs):
        # We don't need to use the parameters, but we accept them to match the real class.
        print(f"[MockNRF24] Radio initialized with payload_size={payload_size}.")
        self.payload_size = payload_size
        self._data_ready = False

    def send(self, payload):
        # Instead of sending over radio, add the data to our shared queue.
        if len(payload) > self.payload_size:
            raise ValueError(f"Payload size {len(payload)} exceeds max {self.payload_size}")
        MockNRF24._airwaves.append(bytes(payload))
        # print(f"[MockNRF24 Sender] Sent: {payload}")

    def wait_until_sent(self):
        # In this simulation, sending is instant. We just wait a tiny bit.
        time.sleep(0.0001)
        return

    def data_ready(self):
        # Is there anything in the "airwaves" for us to receive?
        return len(MockNRF24._airwaves) > 0

    def get_payload(self):
        # Get data from the shared "airwaves" queue.
        if self.data_ready():
            payload = MockNRF24._airwaves.popleft()
            # print(f"[MockNRF24 Receiver] Received: {payload}")
            return payload
        return None

    def power_down(self):
        print("[MockNRF24] Radio powered down.")
    
    # Add other methods that are called in the scripts but do nothing.
    def set_address_bytes(self, length): pass
    def set_retransmission(self, delay, count): pass
    def open_writing_pipe(self, address): pass
    def open_reading_pipe(self, pipe_num, address): pass
    def show_registers(self): pass

# =============================================================================
# PARTE 2: LÓGICA DEL EMISOR Y RECEPTOR
# Adaptamos las funciones originales para que usen nuestros objetos simulados.
# =============================================================================

def run_sender(nrf_sender, filepath):
    """Simulates the sender's logic."""
    print("\n--- INICIANDO SIMULACIÓN DEL EMISOR ---")
    try:
        print(f"Reading file: {filepath}")
        with open(filepath, 'rb') as f:
            file_data = f.read()
        
        file_size = len(file_data)
        print(f"File read. Total size: {file_size} bytes.")
        
        chunk_size = 32
        chunks_sent = 0
        for i in range(0, file_size, chunk_size):
            chunk = file_data[i:i + chunk_size]
            nrf_sender.send(chunk)
            nrf_sender.wait_until_sent()
            chunks_sent += 1
            progress = (chunks_sent * chunk_size * 100) / file_size
            print(f"Progress: {min(100, progress):.2f}%", end='\r', flush=True)

        # Send an empty packet for EOF.
        nrf_sender.send(b'')
        nrf_sender.wait_until_sent()
        
        print("\n[Sender] Transfer complete.")
    finally:
        nrf_sender.power_down()

def run_receiver(nrf_receiver, output_filepath):
    """Simulates the receiver's logic."""
    print("\n\n--- INICIANDO SIMULACIÓN DEL RECEPTOR ---")
    try:
        print(f"Listening for data... Will save to: {output_filepath}")
        with open(output_filepath, 'wb') as f:
            bytes_received = 0
            while True:
                if nrf_receiver.data_ready():
                    payload = nrf_receiver.get_payload()
                    if len(payload) == 0:
                        print(f"\n[Receiver] End-of-file signal received. Total: {bytes_received} bytes.")
                        break
                    f.write(payload)
                    bytes_received += len(payload)
                    print(f"Received {bytes_received} bytes...", end='\r', flush=True)
                else:
                    # If we run out of data in the queue, break the loop.
                    # This prevents an infinite loop in the simulation.
                    break
        print(f"\n[Receiver] File saved successfully.")
    finally:
        nrf_receiver.power_down()

# =============================================================================
# PARTE 3: EJECUCIÓN DE LA SIMULACIÓN
# =============================================================================

if __name__ == "__main__":
    # --- Configuración ---
    original_file = "test_simulation.txt"
    received_file = "received_simulation.txt"

    # --- 1. Crear un archivo de prueba ---
    print("--- PREPARANDO LA SIMULACIÓN ---")
    file_content = "This is a test file for the NRF24 simulation. " * 5
    with open(original_file, "w") as f:
        f.write(file_content)
    print(f"Created test file: '{original_file}'")

    # --- 2. Crear los objetos simulados ---
    # Ambos "radios" comparten la misma cola de "ondas de radio"
    mock_pi_sender = MockPi("localhost", 8888)
    mock_nrf_sender = MockNRF24(mock_pi_sender, ce=25, payload_size=32)
    
    mock_pi_receiver = MockPi("localhost", 8888)
    mock_nrf_receiver = MockNRF24(mock_pi_receiver, ce=25, payload_size=32)

    # --- 3. Ejecutar la lógica ---
    run_sender(mock_nrf_sender, original_file)
    run_receiver(mock_nrf_receiver, received_file)

    # --- 4. Verificar el resultado ---
    print("\n--- VERIFICANDO RESULTADOS ---")
    with open(original_file, 'r') as f1, open(received_file, 'r') as f2:
        content1 = f1.read()
        content2 = f2.read()
        if content1 == content2:
            print("✅ Éxito: El archivo original y el recibido son idénticos.")
        else:
            print("❌ Fracaso: Los archivos son diferentes.")
    
    # --- 5. Limpiar ---
    os.remove(original_file)
    os.remove(received_file)
    print("Archivos de simulación eliminados.")