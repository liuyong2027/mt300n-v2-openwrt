//go:build linux

package main

import (
	"crypto/sha256"
	"debug/elf"
	"encoding/binary"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func guardELFFixture(t *testing.T, machine elf.Machine, dynamic bool) (string, []byte) {
	t.Helper()
	data := make([]byte, 64)
	copy(data, []byte{0x7f, 'E', 'L', 'F', 2, 1, 1})
	binary.LittleEndian.PutUint16(data[16:], uint16(elf.ET_EXEC))
	binary.LittleEndian.PutUint16(data[18:], uint16(machine))
	binary.LittleEndian.PutUint32(data[20:], 1)
	binary.LittleEndian.PutUint16(data[52:], 64)
	if dynamic {
		binary.LittleEndian.PutUint64(data[32:], 64)
		binary.LittleEndian.PutUint16(data[54:], 56)
		binary.LittleEndian.PutUint16(data[56:], 1)
		data = append(data, make([]byte, 56)...)
		binary.LittleEndian.PutUint32(data[64:], uint32(elf.PT_INTERP))
	}
	path := filepath.Join(t.TempDir(), "quantum-fixture")
	if e := os.WriteFile(path, data, 0600); e != nil {
		t.Fatal(e)
	}
	return path, data
}

func setGuardHash(t *testing.T, data []byte) {
	t.Helper()
	old := quantumHash
	t.Cleanup(func() { quantumHash = old })
	h := sha256.Sum256(data)
	quantumHash = hex.EncodeToString(h[:])
}

func TestBinaryGuardAcceptsBoundARM64AndRejectsTampering(t *testing.T) {
	path, data := guardELFFixture(t, elf.EM_AARCH64, false)
	setGuardHash(t, data)
	if e := verifyBinary(path); e != nil {
		t.Fatal(e)
	}
	data = append(data, 1)
	if e := os.WriteFile(path, data, 0600); e != nil {
		t.Fatal(e)
	}
	if e := verifyBinary(path); e == nil || !strings.Contains(e.Error(), "SHA256 mismatch") {
		t.Fatalf("modified executable was not rejected by hash guard: %v", e)
	}
}

func TestBinaryGuardRejectsUnboundBuild(t *testing.T) {
	path, data := guardELFFixture(t, elf.EM_AARCH64, false)
	setGuardHash(t, data)
	quantumHash = ""
	if e := verifyBinary(path); e == nil || !strings.Contains(e.Error(), "not bound") {
		t.Fatalf("unbound helper was not rejected: %v", e)
	}
}

func TestBinaryGuardRejectsWrongArchitecture(t *testing.T) {
	path, data := guardELFFixture(t, elf.EM_X86_64, false)
	setGuardHash(t, data)
	if e := verifyBinary(path); e == nil || !strings.Contains(e.Error(), "not AArch64") {
		t.Fatalf("wrong architecture was not rejected: %v", e)
	}
}

func TestBinaryGuardRejectsDynamicExecutable(t *testing.T) {
	path, data := guardELFFixture(t, elf.EM_AARCH64, true)
	setGuardHash(t, data)
	if e := verifyBinary(path); e == nil || !strings.Contains(e.Error(), "dynamic ELF") {
		t.Fatalf("dynamic executable was not rejected: %v", e)
	}
}
