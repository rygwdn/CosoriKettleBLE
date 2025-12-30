#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "bleak",
#     "click",
#     "rich",
#     "aioconsole",
# ]
# ///

"""Interactive CLI for Cosori Kettle BLE control."""

import asyncio
import logging
import sys
from typing import Optional
from pathlib import Path

import click
from aioconsole import ainput
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from bleak import BLEDevice

# Add parent directory to path for imports when run as script
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from cosori_kettle.client import CosoriKettleClient

console = Console()
logger = logging.getLogger(__name__)


class KettleCLI:
    """Interactive CLI for Cosori Kettle."""
    
    def __init__(self):
        self.client: Optional[CosoriKettleClient] = None
        self.running = False
    
    def _on_state_change(self, changes: dict) -> None:
        """Callback for state changes."""
        for field, (old_val, new_val) in changes.items():
            if field == 'heating':
                status = "ON" if new_val else "OFF"
                console.print(f"[yellow]Heating: {status}[/yellow]")
            elif field == 'on_base':
                status = "ON BASE" if new_val else "OFF BASE"
                console.print(f"[cyan]{status}[/cyan]")
            elif field == 'temperature_f':
                console.print(f"[green]Temperature: {new_val}°F[/green]")
            elif field == 'setpoint_f':
                console.print(f"[blue]Setpoint: {new_val}°F[/blue]")
    
    async def scan(self) -> list[BLEDevice]:
        """Scan for kettles."""
        with console.status("[bold green]Scanning for Cosori kettles..."):
            devices = await self.client.scan()
        
        if not devices:
            console.print("[red]No Cosori kettles found[/red]")
            return []
        
        table = Table(title="Found Devices")
        table.add_column("Index", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Address", style="yellow")
        
        for i, device in enumerate(devices, 1):
            table.add_row(str(i), device.name or "Unknown", device.address)
        
        console.print(table)
        return devices
    
    async def connect(self, address: Optional[str] = None) -> bool:
        """Connect to kettle."""
        if self.client and self.client.is_connected():
            console.print("[yellow]Already connected[/yellow]")
            return True
        
        if not self.client:
            self.client = CosoriKettleClient(on_state_change=self._on_state_change)
        
        device = None
        if address:
            # Find by address
            devices = await self.client.scan()
            device = next((d for d in devices if d.address.upper() == address.upper()), None)
            if not device:
                console.print(f"[red]Device {address} not found[/red]")
                return False
        else:
            # Find by name
            device = await self.client.find_device("Cosori Gooseneck Kettle")
            if not device:
                console.print("[red]Cosori Gooseneck Kettle not found[/red]")
                return False
        
        console.print(f"[green]Connecting to {device.name} ({device.address})...[/green]")
        success = await self.client.connect(device)
        
        if success:
            console.print("[bold green]Connected![/bold green]")
            # Wait for registration
            for _ in range(50):  # Wait up to 5 seconds
                if self.client.registration_complete:
                    break
                await asyncio.sleep(0.1)
            return True
        else:
            console.print("[red]Connection failed[/red]")
            return False
    
    async def show_status(self) -> None:
        """Display current status."""
        if not self.client or not self.client.is_connected():
            console.print("[red]Not connected[/red]")
            return
        
        state = self.client.state
        
        table = Table(title="Kettle Status", show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Connected", "✓" if state.connected else "✗")
        table.add_row("Temperature", f"{state.current_temp_f:.0f}°F")
        table.add_row("Setpoint", f"{state.setpoint_f:.0f}°F")
        table.add_row("Target Setpoint", f"{state.target_setpoint_f:.0f}°F")
        table.add_row("Heating", "ON" if state.heating else "OFF")
        
        on_base_str = "Yes" if state.on_base else "No" if state.on_base is False else "Unknown"
        table.add_row("On Base", on_base_str)
        
        if state.last_update > 0:
            import time
            age = time.time() - state.last_update
            table.add_row("Last Update", f"{age:.1f}s ago")
        
        console.print(table)
    
    async def set_temperature(self, temp: float) -> None:
        """Set target temperature."""
        if not self.client or not self.client.is_connected():
            console.print("[red]Not connected[/red]")
            return
        
        await self.client.set_target_temperature(temp)
        console.print(f"[green]Target temperature set to {temp:.0f}°F[/green]")
    
    async def start(self) -> None:
        """Start heating."""
        if not self.client or not self.client.is_connected():
            console.print("[red]Not connected[/red]")
            return
        
        await self.client.start_heating()
        console.print("[green]Heating started[/green]")
    
    async def stop(self) -> None:
        """Stop heating."""
        if not self.client or not self.client.is_connected():
            console.print("[red]Not connected[/red]")
            return
        
        await self.client.stop_heating()
        console.print("[yellow]Stopping heating...[/yellow]")
    
    async def request_status(self) -> None:
        """Send status request command."""
        if not self.client or not self.client.is_connected():
            console.print("[red]Not connected[/red]")
            return
        
        await self.client.request_status()
        console.print("[green]Status request sent[/green]")
    
    async def monitor(self) -> None:
        """Monitor status continuously."""
        if not self.client or not self.client.is_connected():
            console.print("[red]Not connected[/red]")
            return
        
        console.print("[yellow]Monitoring (press Ctrl+C to stop)...[/yellow]")
        
        try:
            with Live(self._create_status_panel(), refresh_per_second=2) as live:
                while True:
                    live.update(self._create_status_panel())
                    await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            console.print("\n[yellow]Monitoring stopped[/yellow]")
    
    def _create_status_panel(self) -> Panel:
        """Create status panel for live display."""
        if not self.client:
            return Panel("[red]Not connected[/red]", title="Status")
        
        state = self.client.state
        
        text = Text()
        text.append("Temperature: ", style="cyan")
        text.append(f"{state.current_temp_f:.0f}°F", style="green bold")
        text.append("\nSetpoint: ", style="cyan")
        text.append(f"{state.setpoint_f:.0f}°F", style="blue")
        text.append("\nTarget: ", style="cyan")
        text.append(f"{state.target_setpoint_f:.0f}°F", style="yellow")
        text.append("\nHeating: ", style="cyan")
        text.append("ON" if state.heating else "OFF", 
                   style="red bold" if state.heating else "green")
        text.append("\nOn Base: ", style="cyan")
        if state.on_base is True:
            text.append("YES", style="green bold")
        elif state.on_base is False:
            text.append("NO", style="red bold")
        else:
            text.append("UNKNOWN", style="yellow")
        
        return Panel(text, title="Kettle Status", border_style="blue")
    
    async def disconnect(self) -> None:
        """Disconnect from kettle."""
        if self.client:
            await self.client.disconnect()
            console.print("[yellow]Disconnected[/yellow]")
    
    async def interactive_loop(self) -> None:
        """Run interactive command loop."""
        console.print("[bold blue]Cosori Kettle BLE CLI[/bold blue]")
        console.print("Type 'help' for commands, 'quit' to exit\n")
        
        self.running = True
        await self.connect()
        
        while self.running:
            try:
                cmd = (await ainput("kettle> ") or "").strip()

                parts = cmd.split()
                command = parts[0].lower()
                args = parts[1:]
                
                if command == "quit" or command == "exit" or not command:
                    await self.disconnect()
                    self.running = False
                    break
                
                elif command == "help":
                    self._show_help()
                
                elif command == "scan":
                    await self.scan()
                
                elif command == "connect":
                    address = args[0] if args else None
                    await self.connect(address)
                
                elif command == "status":
                    await self.show_status()
                
                elif command == "set":
                    if not args:
                        console.print("[red]Usage: set <temperature_f>[/red]")
                    else:
                        try:
                            temp = float(args[0])
                            await self.set_temperature(temp)
                        except ValueError:
                            console.print("[red]Invalid temperature[/red]")
                
                elif command == "start":
                    await self.start()
                
                elif command == "stop":
                    await self.stop()
                
                elif command == "status":
                    await self.request_status()
                
                elif command == "monitor":
                    await self.monitor()
                
                elif command == "disconnect":
                    await self.disconnect()
                
                else:
                    console.print(f"[red]Unknown command: {command}[/red]")
                    console.print("Type 'help' for available commands")
            
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Interrupted[/yellow]")
                await self.disconnect()
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                logger.exception("Command error")
                await self.disconnect()
                break
    
    def _show_help(self) -> None:
        """Show help message."""
        table = Table(title="Commands", show_header=True)
        table.add_column("Command", style="cyan")
        table.add_column("Description", style="green")
        
        table.add_row("scan", "Scan for Cosori kettles")
        table.add_row("connect [address]", "Connect to kettle (by address or auto-detect)")
        table.add_row("status", "Show current status")
        table.add_row("set <temp>", "Set target temperature (104-212°F)")
        table.add_row("start", "Start heating to target temperature")
        table.add_row("stop", "Stop heating")
        table.add_row("status", "Send status request command")
        table.add_row("monitor", "Monitor status continuously")
        table.add_row("disconnect", "Disconnect from kettle")
        table.add_row("quit", "Exit CLI")
        
        console.print(table)


@click.command()
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option("--address", help="Connect directly to this MAC address")
@click.option("--command", help="Execute single command and exit")
def main(debug: bool, address: Optional[str], command: Optional[str]):
    """Cosori Kettle BLE Control CLI."""
    
    # Setup logging
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    cli = KettleCLI()
    
    async def run():
        if command:
            # Single command mode
            if command == "scan":
                cli.client = CosoriKettleClient()
                await cli.scan()
            elif command == "status" and address:
                await cli.connect(address)
                await cli.show_status()
                await cli.disconnect()
            else:
                console.print(f"[red]Unknown command or missing address: {command}[/red]")
        elif address:
            # Connect and run interactive
            await cli.connect(address)
            await cli.interactive_loop()
        else:
            # Interactive mode
            await cli.interactive_loop()
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Exiting...[/yellow]")
        asyncio.run(cli.disconnect())


if __name__ == "__main__":
    main()
